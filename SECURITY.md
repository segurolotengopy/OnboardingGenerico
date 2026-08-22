# Política de seguridad

Este sistema procesa documentos de identidad y datos biométricos. Un fallo de seguridad aquí no es una incidencia de servicio: es una brecha de datos de categoría especial, con obligación de notificación en varias jurisdicciones.

## Reportar una vulnerabilidad

**No abra un issue público.** Escriba a los mantenedores del repositorio a través de la función de *private vulnerability reporting* de GitHub, o por el canal privado que su organización tenga establecido.

Incluya, en la medida de lo posible:

- Componente afectado y versión o commit.
- Descripción del impacto y del peor escenario realista.
- Pasos de reproducción y prueba de concepto.
- Si la explotación permite cruzar la frontera entre inquilinos (esto eleva la severidad al máximo automáticamente).

**No incluya datos personales reales en el reporte.** Use datos sintéticos para reproducir.

### Compromisos

| Etapa | Plazo objetivo |
|---|---|
| Acuse de recibo | 3 días hábiles |
| Evaluación inicial y severidad asignada | 10 días hábiles |
| Corrección para severidad crítica o alta | Según acuerdo, con mitigación provisional inmediata |
| Divulgación coordinada | Tras la corrección, de común acuerdo con quien reporta |

## Alcance

Entra en alcance el código de este repositorio, sus plantillas de infraestructura y sus configuraciones por defecto. Los servicios gestionados de AWS y Google Cloud tienen sus propios canales; repórteles directamente lo que sea suyo.

## Clases de vulnerabilidad de máxima prioridad

Derivadas del [modelo de amenazas](docs/14-modelo-de-amenazas.md):

1. **Cruce de frontera entre inquilinos** — cualquier ruta por la que un inquilino pueda leer, escribir o inferir datos de otro. Incluye fugas por mensajes de error, por métricas, por colisiones de *beacon* de búsqueda y por reutilización de material criptográfico en caché.
2. **Elusión del cifrado por inquilino** — cualquier ruta que permita descifrar sin el `tenant_id` correcto como Associated Data.
3. **Inyección de instrucciones a través del contenido del documento** — texto colocado en un documento de identidad que el modelo de lenguaje interprete como instrucción durante la extracción semántica.
4. **Falsificación de la evidencia de verificación** — manipulación de la cadena de auditoría encadenada por hash, o inyección de evidencia que no provenga de una captura real.
5. **Elusión de la detección de vivacidad** — inyección de medios en el canal de cámara, reproducción de sesión, o deepfake. Nótese que la certificación PAD de ISO/IEC 30107-3 **no cubre** ataques de inyección.
6. **Fuga de datos personales en registros, trazas o métricas.**
7. **Envenenamiento del Registro de Capacidades** — alteración de una especificación de flujo para degradar o desactivar un control.

## Controles vigentes en el repositorio

- `gitleaks` y `detect-private-key` en los *hooks* de pre-commit y en integración continua.
- Análisis estático de seguridad (`ruff` con reglas `S`, más el flujo de CI de seguridad) y análisis de dependencias.
- Prohibición de versionar datos personales reales, incluidos los propios.
- Redacción de datos personales en el registro estructurado, activada por defecto.
- Prueba de arquitectura que impide que el núcleo importe SDK de nube.

## Lo que este proyecto no le dará

No se distribuyen credenciales, ni conjuntos de datos de documentos reales, ni modelos con licencia restringida. Antes de incorporar pesos de modelos de terceros, consulte [ADR-0012](docs/adr/0012-politica-de-licencias-de-terceros.md): la licencia de los pesos se evalúa por separado de la licencia del código, y varios modelos habituales en este dominio son de uso exclusivamente investigativo.
