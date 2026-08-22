"""Registro y resolución de especificaciones de flujo.

Reglas de precedencia (doc 04 §5.2), en este orden:

1. **Especificidad antes que prioridad.** Una spec con ``countries: [MX]``
   gana sobre una con ``countries: ['*']``, sea cual sea `priority`.
2. **Tenant antes que global.** Siempre.
3. **`priority` desempata** solo entre specs con idéntica especificidad y
   ámbito. Un empate a especificidad *y* prioridad es un **error de
   publicación**, no una ambigüedad resuelta al azar: se detecta al publicar
   la segunda spec.
4. **No hay herencia parcial ni composición.** Una spec se aplica completa;
   la herencia de fragmentos produce especificaciones efectivas que nadie
   puede leer, y eso destruye la auditabilidad.

Entre versiones de la misma clave gana siempre la **semver mayor**.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..domain.value_objects import FlowSpecRef
from ..errors import AmbiguousFlowSpecError, NoApplicableFlowSpecError, SpecValidationError
from .spec import FlowSpec

GLOBAL_TENANT: str = "GLOBAL"


def parse_semver(version: str) -> tuple[int, int, int]:
    """Convierte `MAJOR.MINOR.PATCH` a tupla comparable."""
    parts = version.split(".")
    if len(parts) != 3:
        raise SpecValidationError("versión semver mal formada", check="V1", path="metadata.version")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def satisfies_range(version: str, version_range: str) -> bool:
    """Comprueba una versión contra un rango `^X.Y`, `~X.Y` o exacto.

    - ``^1.4``: compatible dentro de la misma mayor, mínimo 1.4.0.
    - ``~1.4``: compatible dentro de la misma menor, mínimo 1.4.0.
    - ``1.4.2``: exacto.
    - vacío: cualquiera.
    """
    if not version_range:
        return True
    target = parse_semver(version)
    operator = version_range[0] if version_range[0] in "^~" else ""
    raw = version_range[1:] if operator else version_range
    pieces = [int(p) for p in raw.split(".")]
    while len(pieces) < 3:
        pieces.append(0)
    floor = (pieces[0], pieces[1], pieces[2])
    if target < floor:
        return False
    if operator == "^":
        return target[0] == floor[0]
    if operator == "~":
        return target[:2] == floor[:2]
    return target == floor


@dataclass(frozen=True, slots=True)
class ResolvedSpec:
    """Especificación seleccionada junto con su referencia congelada."""

    spec: FlowSpec
    ref: FlowSpecRef
    specificity: int
    tenant_scoped: bool

    @property
    def rank(self) -> tuple[int, int, int, tuple[int, int, int]]:
        """Orden de preferencia; mayor es mejor."""
        return (
            1 if self.tenant_scoped else 0,
            self.specificity,
            self.spec.resolution.priority,
            parse_semver(self.spec.version),
        )


class FlowSpecRegistry:
    """Registro en memoria de especificaciones publicadas.

    El adaptador de persistencia guarda los documentos; esta clase encapsula
    la lógica de resolución, que es de dominio y no debe reimplementarse en
    DynamoDB y en Firestore.
    """

    __slots__ = ("_specs",)

    def __init__(self, specs: Iterable[FlowSpec] = ()) -> None:
        self._specs: dict[tuple[str, str, str], FlowSpec] = {}
        for spec in specs:
            self.publish(spec)

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def specs(self) -> tuple[FlowSpec, ...]:
        return tuple(self._specs.values())

    # -- Publicación -------------------------------------------------------

    def publish(self, spec: FlowSpec) -> FlowSpecRef:
        """Publica una versión. Es inmutable: republicar la misma falla.

        También detecta el empate de especificidad y prioridad con otra spec
        del mismo ámbito, que es un error de publicación (regla 3).
        """
        identity = (spec.tenant, spec.name, spec.version)
        existing = self._specs.get(identity)
        if existing is not None:
            if existing.content_hash != spec.content_hash:
                raise SpecValidationError(
                    "una versión publicada es inmutable: cambie MAJOR/MINOR/PATCH para modificarla",
                    check="V1",
                    path="$.metadata.version",
                )
            return self._ref(existing)

        self._assert_no_ambiguity(spec)
        self._specs[identity] = spec
        return self._ref(spec)

    def _assert_no_ambiguity(self, spec: FlowSpec) -> None:
        for other in self._specs.values():
            if other.tenant != spec.tenant or other.name == spec.name:
                continue
            if other.resolution.specificity != spec.resolution.specificity:
                continue
            if other.resolution.priority != spec.resolution.priority:
                continue
            if not _overlaps(spec, other):
                continue
            raise AmbiguousFlowSpecError(
                "dos especificaciones empatan en especificidad y prioridad para el mismo ámbito; "
                "ajuste 'priority' o acote 'resolution'",
                existing=other.key,
                incoming=spec.key,
                specificity=spec.resolution.specificity,
                priority=spec.resolution.priority,
            )

    # -- Resolución --------------------------------------------------------

    def resolve(
        self, *, tenant_id: str, country: str, document_type: str, tier: str = "IAL2"
    ) -> ResolvedSpec:
        """Resuelve la spec vigente para la clave compuesta.

        Lanza `NoApplicableFlowSpecError` si nada aplica: la sesión **no se
        crea**, se responde 422.
        """
        candidates = self.candidates(
            tenant_id=tenant_id, country=country, document_type=document_type, tier=tier
        )
        if not candidates:
            raise NoApplicableFlowSpecError(
                "ninguna especificación de flujo aplica a la clave solicitada",
                tenant_id=tenant_id,
                country=country,
                document_type=document_type,
                tier=tier,
            )
        best = candidates[0]
        if len(candidates) > 1 and candidates[1].rank == best.rank:
            raise AmbiguousFlowSpecError(
                "empate irresoluble entre especificaciones aplicables",
                first=best.spec.key,
                second=candidates[1].spec.key,
            )
        return best

    def candidates(
        self, *, tenant_id: str, country: str, document_type: str, tier: str = "IAL2"
    ) -> tuple[ResolvedSpec, ...]:
        """Todas las specs aplicables, de la más preferente a la menos."""
        matches: list[ResolvedSpec] = []
        latest: dict[tuple[str, str], FlowSpec] = {}
        for spec in self._specs.values():
            if spec.tenant not in {tenant_id, GLOBAL_TENANT}:
                continue
            if not spec.resolution.matches(country=country, document_type=document_type, tier=tier):
                continue
            identity = (spec.tenant, spec.name)
            current = latest.get(identity)
            if current is None or parse_semver(spec.version) > parse_semver(current.version):
                latest[identity] = spec

        for spec in latest.values():
            matches.append(
                ResolvedSpec(
                    spec=spec,
                    ref=self._ref(spec),
                    specificity=spec.resolution.specificity,
                    tenant_scoped=spec.tenant != GLOBAL_TENANT,
                )
            )
        matches.sort(key=lambda item: item.rank, reverse=True)
        return tuple(matches)

    def get(self, tenant: str, name: str, version: str) -> FlowSpec | None:
        return self._specs.get((tenant, name, version))

    def list_versions(self, tenant: str, name: str) -> tuple[str, ...]:
        versions = [v for (t, n, v) in self._specs if t == tenant and n == name]
        versions.sort(key=parse_semver)
        return tuple(versions)

    @staticmethod
    def _ref(spec: FlowSpec) -> FlowSpecRef:
        return FlowSpecRef(key=spec.key, version=spec.version, content_hash=spec.content_hash)


def _overlaps(left: FlowSpec, right: FlowSpec) -> bool:
    """`True` si dos specs pueden resolver la misma clave concreta."""
    return (
        _dimension_overlaps(left.resolution.countries, right.resolution.countries)
        and _dimension_overlaps(left.resolution.document_types, right.resolution.document_types)
        and _dimension_overlaps(left.resolution.tiers, right.resolution.tiers)
    )


def _dimension_overlaps(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if "*" in left or "*" in right:
        return True
    return bool(set(left) & set(right))


def build_registry_from_documents(documents: Iterable[Mapping[str, object]]) -> FlowSpecRegistry:
    """Construye el registro a partir de documentos JSON ya cargados."""
    registry = FlowSpecRegistry()
    for document in documents:
        registry.publish(FlowSpec.parse(document))
    return registry


__all__ = [
    "GLOBAL_TENANT",
    "FlowSpecRegistry",
    "ResolvedSpec",
    "build_registry_from_documents",
    "parse_semver",
    "satisfies_range",
]
