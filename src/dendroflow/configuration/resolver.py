"""Compatibility façade for CONFIG resolution."""

from .resolution.aliases import (
    AliasRegistry as _AliasRegistry,
)
from .resolution.aliases import (
    DeclarationAlias as _DeclarationAlias,
)
from .resolution.aliases import (
    ReferenceAlias as _ReferenceAlias,
)
from .resolution.aliases import (
    build_alias_registry as _build_alias_registry,
)
from .resolution.metadata import (
    resolve_deployment_declarations as _resolve_deployment_declarations,
)
from .resolution.metadata import (
    resolve_deployment_reference_aliases as _resolve_deployment_reference_aliases,
)
from .resolution.metadata import (
    resolve_location_declarations as _resolve_location_declarations,
)
from .resolution.metadata import (
    resolve_location_label_declarations as _resolve_location_label_declarations,
)
from .resolution.metadata import (
    resolve_location_reference_aliases as _resolve_location_reference_aliases,
)
from .resolution.metadata import (
    resolve_sensor_declarations as _resolve_sensor_declarations,
)
from .resolution.metadata import (
    resolve_sensor_model_declarations as _resolve_sensor_model_declarations,
)
from .resolution.metadata import (
    resolve_sensor_model_reference_aliases as _resolve_sensor_model_reference_aliases,
)
from .resolution.metadata import (
    resolve_sensor_reference_aliases as _resolve_sensor_reference_aliases,
)
from .resolution.metadata import (
    resolve_simple_declarations as _resolve_simple_declarations,
)
from .resolution.metadata import (
    resolve_simple_reference_aliases as _resolve_simple_reference_aliases,
)
from .resolution.orchestration import (
    resolve_metadata_config as _resolve_metadata_config,
)

AliasRegistry = _AliasRegistry
DeclarationAlias = _DeclarationAlias
ReferenceAlias = _ReferenceAlias
build_alias_registry = _build_alias_registry

resolve_simple_reference_aliases = _resolve_simple_reference_aliases
resolve_simple_declarations = _resolve_simple_declarations

resolve_sensor_model_reference_aliases = (
    _resolve_sensor_model_reference_aliases
)
resolve_sensor_model_declarations = _resolve_sensor_model_declarations

resolve_sensor_reference_aliases = _resolve_sensor_reference_aliases
resolve_sensor_declarations = _resolve_sensor_declarations

resolve_location_reference_aliases = _resolve_location_reference_aliases
resolve_location_declarations = _resolve_location_declarations
resolve_location_label_declarations = (
    _resolve_location_label_declarations
)

resolve_deployment_reference_aliases = (
    _resolve_deployment_reference_aliases
)
resolve_deployment_declarations = _resolve_deployment_declarations

resolve_metadata_config = _resolve_metadata_config

