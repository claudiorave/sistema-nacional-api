"""Mutaciones nacionales. Orden de locks: proyecto → ONG → inventario.

La revisión de credenciales y cualquier modificación de inventario o habilitación
toman el mismo lock de ONG. Todas las listas de locks se ordenan por UUID.
"""

import hashlib
import json
from collections import defaultdict

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .exceptions import Conflict
from .models import (
    RISK_RANK,
    AuditEvent,
    Commitment,
    CommitmentItem,
    IdempotencyRecord,
    Inventory,
    Organization,
    Project,
    ResourceType,
    RiskLevel,
    User,
)
from .permissions import is_national


def audit(actor, action, *, organization=None, project=None, detail=None):
    return AuditEvent.objects.create(
        actor=actor, action=action, organization=organization, project=project, detail=detail or {}
    )


def risk_levels(maximum):
    return [risk for risk in RiskLevel.values if RISK_RANK[risk] <= RISK_RANK[maximum]]


def competence_profile(organization, *, resources=None, evaluated_at=None):
    evaluated_at = evaluated_at or timezone.now()
    today = evaluated_at.date()
    capabilities = {}
    observations = []
    for cert in organization.certifications.select_related("certification_type").order_by("id"):
        if cert.revoked_at:
            state = "revoked"
        elif cert.valid_from > today:
            state = "not_yet_valid"
        elif cert.valid_until < today:
            state = "expired"
        else:
            state = "current"
        observations.append(
            {"certification": str(cert.pk), "state": state, "valid_until": cert.valid_until.isoformat()}
        )
        if state != "current" or organization.status != Organization.Status.ENABLED:
            continue
        kind = cert.certification_type
        capability = capabilities.setdefault(
            kind.capability_code,
            {
                "capability_code": kind.capability_code,
                "max_risk_level": kind.max_risk_level,
                "certification_ids": [],
            },
        )
        if RISK_RANK[kind.max_risk_level] > RISK_RANK[capability["max_risk_level"]]:
            capability["max_risk_level"] = kind.max_risk_level
        capability["certification_ids"].append(str(cert.pk))
    for capability in capabilities.values():
        capability["allowed_risk_levels"] = risk_levels(capability["max_risk_level"])
    support = {}
    if organization.status == Organization.Status.ENABLED:
        resources = list(resources) if resources is not None else list(ResourceType.objects.all())
        for resource in resources:
            if not resource.support_allowed:
                continue
            previous = support.get(resource.capability_code)
            if previous and RISK_RANK[previous["max_risk_level"]] >= RISK_RANK[resource.support_max_risk]:
                continue
            support[resource.capability_code] = {
                "capability_code": resource.capability_code,
                "max_risk_level": resource.support_max_risk,
                "allowed_risk_levels": risk_levels(resource.support_max_risk),
                "certification_ids": [],
            }
    return {
        "organization": str(organization.pk),
        "organization_status": organization.status,
        "evaluated_at": evaluated_at.isoformat(),
        "capabilities": [capabilities[key] for key in sorted(capabilities)],
        "support_capabilities": [support[key] for key in sorted(support)],
        "credential_observations": observations,
    }


def evaluation_context(items, actor, *, lock=False):
    organization_ids = {item["organization"] for item in items}
    if actor.role == User.Role.NGO and not actor.is_superuser and organization_ids != {actor.organization_id}:
        raise PermissionDenied("Una ONG solo puede validar sus propios recursos.")
    org_query = Organization.objects.filter(pk__in=organization_ids).order_by("pk")
    if lock:
        org_query = org_query.select_for_update()
    organizations = {org.pk: org for org in org_query}
    if len(organizations) != len(organization_ids):
        raise ValidationError({"items": "Hay ONGs nacionales inexistentes. Use sus UUID nacionales."})
    resource_codes = {item["resource_code"] for item in items}
    resources = {r.code: r for r in ResourceType.objects.filter(code__in=resource_codes)}
    if len(resources) != len(resource_codes):
        raise ValidationError({"items": "Hay códigos de recursos inexistentes."})
    inventory_query = Inventory.objects.filter(
        organization_id__in=organization_ids,
        resource_type_id__in=[r.pk for r in resources.values()],
    ).order_by("pk")
    if lock:
        inventory_query = inventory_query.select_for_update()
    stocks = {(stock.organization_id, stock.resource_type_id): stock for stock in inventory_query}
    return organizations, resources, stocks


def evaluate_items(items, organizations, resources, stocks):
    now = timezone.now()
    profiles = {
        org_id: competence_profile(org, resources=resources.values(), evaluated_at=now)
        for org_id, org in organizations.items()
    }
    used = defaultdict(int)
    results = []
    for item in items:
        resource = resources[item["resource_code"]]
        profile = profiles[item["organization"]]
        capabilities = {c["capability_code"]: c for c in profile["capabilities"]}
        main = capabilities.get(resource.capability_code, {}).get("allowed_risk_levels", [])
        support = (
            risk_levels(resource.support_max_risk)
            if resource.support_allowed and profile["organization_status"] == "enabled"
            else []
        )
        key = (item["organization"], resource.pk)
        stock = stocks.get(key)
        available = stock.available_quantity if stock else 0
        remainder = max(0, available - used[key])
        recommendation = "main" if item["risk_level"] in main else "support" if support else "none"
        observations = []
        if profile["organization_status"] != "enabled":
            observations.append("organization_not_enabled")
        if item["risk_level"] not in main:
            observations.append("main_risk_not_authorized")
        if recommendation == "support" and item["risk_level"] not in support:
            observations.append("adapt_to_support_at_a_permitted_risk_level")
        if item["quantity"] > remainder:
            observations.append("insufficient_available_resources")
        results.append(
            {
                **{
                    key: str(value) if key == "organization" else value
                    for key, value in item.items()
                    if key != "assignment"
                },
                "unit": resource.unit,
                "available_quantity": available,
                "max_assignable_quantity": min(item["quantity"], remainder)
                if recommendation != "none"
                else 0,
                "main_allowed_risk_levels": main,
                "support_allowed_risk_levels": support,
                "recommended_assignment": recommendation,
                "observations": observations,
                "competence": profile,
            }
        )
        used[key] += item["quantity"]
    return {"evaluated_at": now.isoformat(), "reserves_resources": False, "items": results}


def validate_resources(items, actor):
    context = evaluation_context(items, actor)
    return evaluate_items(items, *context)


def request_digest(data):
    # El orden de las líneas no altera el significado de una adjudicación.
    normalized = {
        "project": data["project"],
        "items": sorted(
            data["items"], key=lambda i: (str(i["organization"]), i["resource_code"], i["lot_ref"])
        ),
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


@transaction.atomic
def commit_resources(data, actor, idempotency_key):
    if actor.role != User.Role.SERVICE:
        raise PermissionDenied("El compromiso requiere la cuenta de integración de Bonita.")
    digest = request_digest(data)
    record, _ = IdempotencyRecord.objects.get_or_create(
        source_system=actor.source_system, key=idempotency_key, defaults={"request_hash": digest}
    )
    record = IdempotencyRecord.objects.select_for_update().get(pk=record.pk)
    if record.request_hash != digest:
        raise Conflict("La clave de idempotencia ya fue usada con una adjudicación diferente.")
    if record.project_id:
        return record.project, False
    if Project.objects.filter(
        source_system=actor.source_system, external_id=data["project"]["external_id"]
    ).exists():
        raise Conflict("Esta emergencia ya tiene una adjudicación nacional. Reintente con su clave original.")
    project = Project.objects.create(source_system=actor.source_system, created_by=actor, **data["project"])
    # El nuevo proyecto es privado a esta transacción hasta el COMMIT.
    organizations, resources, stocks = evaluation_context(data["items"], actor, lock=True)
    evaluation = evaluate_items(data["items"], organizations, resources, stocks)
    failures = []
    for item, evaluated in zip(data["items"], evaluation["items"], strict=True):
        permitted_risks = evaluated[f"{item['assignment']}_allowed_risk_levels"]
        if (
            item["risk_level"] not in permitted_risks
            or item["quantity"] > evaluated["max_assignable_quantity"]
        ):
            failures.append(evaluated)
        if RISK_RANK[item["risk_level"]] > RISK_RANK[project.risk_level]:
            raise ValidationError("El riesgo de una actividad no puede exceder el riesgo del proyecto.")
    if failures:
        raise Conflict(
            {
                "detail": "La adjudicación requiere adaptación o excede la disponibilidad actual. No se reservó ningún recurso.",
                "items": failures,
            }
        )
    commitments = {
        org_id: Commitment.objects.create(project=project, organization=organizations[org_id])
        for org_id in sorted(organizations)
    }
    totals = defaultdict(int)
    for item, evaluated in zip(data["items"], evaluation["items"], strict=True):
        stock = stocks[(item["organization"], resources[item["resource_code"]].pk)]
        totals[stock.pk] += item["quantity"]
        CommitmentItem.objects.create(
            commitment=commitments[item["organization"]],
            inventory=stock,
            lot_ref=item["lot_ref"],
            quantity=item["quantity"],
            assignment=item["assignment"],
            risk_level=item["risk_level"],
            competence_snapshot=evaluated["competence"],
        )
    for stock in sorted(stocks.values(), key=lambda s: s.pk):
        if stock.pk in totals:
            stock.reserved_quantity += totals[stock.pk]
            stock.version += 1
            stock.save(update_fields=["reserved_quantity", "version", "updated_at"])
    record.project = project
    record.save(update_fields=["project"])
    audit(
        actor,
        "project.committed",
        project=project,
        detail={"organization_count": len(commitments), "item_count": len(data["items"])},
    )
    return project, True


def authorize_project(actor, project, *, organization_id=None):
    if is_national(actor):
        return
    if actor.role == User.Role.SERVICE and actor.source_system_id == project.source_system_id:
        return
    if actor.role == User.Role.NGO and organization_id == actor.organization_id:
        return
    raise PermissionDenied("No tiene permiso para finalizar esta actividad o proyecto.")


@transaction.atomic
def complete_commitment(commitment_id, actor, notes):
    target = get_object_or_404(Commitment, pk=commitment_id)
    project = Project.objects.select_for_update().get(pk=target.project_id)
    authorize_project(actor, project, organization_id=target.organization_id)
    Organization.objects.select_for_update().get(pk=target.organization_id)
    target.refresh_from_db()
    if target.status == Commitment.Status.COMPLETED:
        return target
    totals = defaultdict(int)
    for item in target.items.all():
        totals[item.inventory_id] += item.quantity
    stocks = Inventory.objects.select_for_update().filter(pk__in=totals).order_by("pk")
    for stock in stocks:
        if stock.reserved_quantity < totals[stock.pk]:
            raise Conflict("Inconsistencia en las reservas. Requiere revisión del operador nacional.")
        stock.reserved_quantity -= totals[stock.pk]
        stock.version += 1
        stock.save(update_fields=["reserved_quantity", "version", "updated_at"])
    target.status = Commitment.Status.COMPLETED
    target.completed_at = timezone.now()
    target.completion_notes = notes
    target.save(update_fields=["status", "completed_at", "completion_notes"])
    audit(
        actor,
        "commitment.completed",
        organization=target.organization,
        project=project,
        detail={"commitment": str(target.pk), "notes": notes},
    )
    return target


@transaction.atomic
def close_project(project_id, actor):
    project = get_object_or_404(Project.objects.select_for_update(), pk=project_id)
    authorize_project(actor, project)
    if project.status == Project.Status.COMPLETED:
        return project
    if project.commitments.filter(status=Commitment.Status.ACTIVE).exists():
        raise Conflict(
            "Todavía existen actividades de ONG sin finalizar. Deben liberarse antes del cierre bilateral."
        )
    project.status = Project.Status.COMPLETED
    project.completed_at = timezone.now()
    project.save(update_fields=["status", "completed_at"])
    audit(actor, "project.closed", project=project)
    return project


@transaction.atomic
def create_inventory(data, actor):
    organization = data.get("organization")
    if actor.role == User.Role.NGO and not actor.is_superuser:
        if organization and organization.pk != actor.organization_id:
            raise PermissionDenied("No puede editar el inventario de otra ONG.")
        organization = actor.organization
    elif not is_national(actor):
        raise PermissionDenied("No puede crear inventarios.")
    if not organization:
        raise ValidationError({"organization": "Un operador nacional debe indicar la ONG."})
    Organization.objects.select_for_update().get(pk=organization.pk)
    stock = Inventory.objects.create(
        organization=organization, resource_type=data["resource_type"], total_quantity=data["total_quantity"]
    )
    audit(
        actor,
        "inventory.created",
        organization=organization,
        detail={"inventory": str(stock.pk), "total_quantity": stock.total_quantity},
    )
    return stock


@transaction.atomic
def update_inventory(stock_id, data, actor):
    initial = get_object_or_404(Inventory, pk=stock_id)
    if not is_national(actor) and (
        actor.role != User.Role.NGO or initial.organization_id != actor.organization_id
    ):
        raise PermissionDenied("No puede editar el inventario de otra ONG.")
    Organization.objects.select_for_update().get(pk=initial.organization_id)
    stock = Inventory.objects.select_for_update().get(pk=stock_id)
    if data["version"] != stock.version:
        raise Conflict("El inventario cambió. Consulte su versión actual antes de editar.")
    if data["total_quantity"] < stock.reserved_quantity:
        raise Conflict("El total no puede ser menor que la cantidad comprometida.")
    before = stock.total_quantity
    stock.total_quantity = data["total_quantity"]
    stock.version += 1
    stock.save(update_fields=["total_quantity", "version", "updated_at"])
    audit(
        actor,
        "inventory.updated",
        organization=stock.organization,
        detail={"inventory": str(stock.pk), "before": before, "after": stock.total_quantity},
    )
    return stock
