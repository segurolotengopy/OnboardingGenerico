## Qué cambia y por qué

<!-- Describa el cambio y su motivación. Enlace al issue o al ADR correspondiente. -->

## Tipo de cambio

- [ ] Funcionalidad nueva
- [ ] Corrección de error
- [ ] Cambio incompatible (requiere nota en el CHANGELOG y posiblemente un ADR)
- [ ] Documentación
- [ ] Infraestructura
- [ ] Refactorización sin cambio de comportamiento

## Verificación

- [ ] `make verificar` pasa localmente (lint, tipos y pruebas)
- [ ] Hay pruebas nuevas o modificadas que fallarían sin este cambio
- [ ] La documentación afectada está actualizada
- [ ] Si toca infraestructura: adjunto la salida de `terraform plan` del entorno `dev`

## Impacto en seguridad y cumplimiento

- [ ] No introduce ninguna ruta por la que un inquilino pueda alcanzar datos de otro
- [ ] No registra datos personales en registros, métricas ni atributos de traza
- [ ] No agrega secretos, credenciales ni datos de identidad reales al repositorio
- [ ] Si cambia el modelo de datos o la criptografía: describo abajo el impacto en el aislamiento por inquilino y en la capacidad de descifrar datos ya escritos

<!-- Descripción del impacto, si aplica: -->

## Componentes de terceros

- [ ] No agrego dependencias nuevas
- [ ] Agrego dependencias y verifiqué su licencia contra la política de [ADR-0012](../docs/adr/0012-politica-de-licencias-de-terceros.md)
- [ ] Si incorpora un modelo: verifiqué la licencia de los **pesos**, que es independiente de la del código

## Decisiones de arquitectura

- [ ] Este cambio es coherente con los ADR vigentes
- [ ] Este cambio contradice un ADR y adjunto el ADR que lo supersede
