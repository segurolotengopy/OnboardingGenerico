# ADR-0008 — OCR genérico más LLM multimodal en lugar de `AnalyzeID` y de los procesadores de identidad de Document AI

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [08 — IA y extracción semántica](../08-ia-y-extraccion-semantica.md) · [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md) · [10 — Multinube](../10-multicloud-aws-gcp.md) · [20 — Fe de erratas](../20-fe-de-erratas-del-spec-original.md) |

## Contexto

El middleware debe extraer campos estructurados —nombres, número de documento, fechas, sexo, nacionalidad, MRZ— de documentos de identidad de **Bolivia, Paraguay, México y la Unión Europea**, con la expectativa de añadir países sin desplegar código ([ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md)).

La ruta aparentemente natural —los servicios de identidad gestionados de cada nube— queda descartada por un hecho verificado y simétrico: **`AnalyzeID` de Amazon Textract está limitado esencialmente a documentos de EE. UU.**, y **los procesadores de identidad de Document AI cubren solo EE. UU.** (licencias de los 50 estados y el Distrito de Columbia, pasaportes, *proofing*), con deprecaciones activas y apagado el **30 de junio de 2026**, incluida la licencia de conducir francesa. **Hay paridad en la limitación**, pero fuera de EE. UU. ninguno de los dos sirve.

Un segundo hecho cambia el signo de la decisión. La brecha más incómoda de un diseño multinube es depender de un componente diferenciador que solo existe en una nube. Aquí ocurre lo contrario: **Claude está disponible en las dos** —Bedrock en AWS, Agent Platform en GCP—, de modo que el componente que hace el trabajo difícil tiene paridad total. La investigación lo señala explícitamente: este enfoque **elimina la brecha**.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Cobertura documental de LATAM y UE | Los procesadores gestionados de identidad no la ofrecen |
| Añadir un documento sin desplegar código | Favorece una plantilla de extracción que sea dato |
| Determinismo y auditabilidad | Un LLM es no determinista; un regulador puede cuestionarlo |
| Coste por documento | El LLM multimodal es más caro por página que el OCR genérico |
| Portabilidad entre nubes | El componente crítico debe existir en ambas |
| Contenido del documento como entrada al modelo | Abre la vía de inyección de prompt desde el propio documento |
| MRZ conforme a ICAO Doc 9303 | Es verificable de forma determinista y no debe delegarse al modelo |

## Opciones consideradas

### Opción A — Procesadores de identidad gestionados

**A favor**
- Cero trabajo de extracción propio: el servicio devuelve campos con nombre y confianza, en salida estructurada y estable.
- Coste por página previsible y menor que el de un LLM multimodal.
- Respaldo del proveedor de nube en mantenimiento y calidad del modelo.

**En contra**
- **Descalificador: cobertura esencialmente estadounidense en ambas nubes.** No cubren cédula boliviana, cédula paraguaya, INE mexicana ni el grueso de documentos europeos.
- Deprecaciones activas con apagado el **30 de junio de 2026**: el proveedor reduce cobertura, no la amplía.
- Añadir un país depende del roadmap del proveedor, y la cobertura difiere entre nubes, introduciendo asimetría funcional en el catálogo de países.

### Opción B — Plantillas por país sobre OCR genérico, con reglas posicionales

OCR genérico (`DetectDocumentText` o Enterprise Document OCR, con precios comparables) y extracción por regiones de interés, expresiones regulares y heurísticas posicionales.

**A favor**
- **Completamente determinista**: la misma entrada produce la misma salida. Es lo más fácil de defender ante un auditor.
- Coste marginal por documento muy bajo una vez escrita la plantilla, con latencia baja y previsible.
- Sin dependencia de un modelo de terceros y sin riesgo de inyección de prompt.

**En contra**
- **El coste de crear y mantener plantillas es el cuello de botella**: cada tipo, emisión y variante regional requiere calibración manual.
- Frágil ante perspectiva, iluminación irregular y desgaste: la geometría fija se rompe con facilidad.
- Un rediseño de documento por parte de un gobierno invalida la plantilla de la noche a la mañana. Escala mal precisamente en el eje donde el producto promete escalar.

### Opción C — Entrenar un modelo propio de extracción documental

**A favor**
- Control total sobre comportamiento, coste de inferencia y evolución.
- Sin dependencia de un proveedor de modelos en el camino crítico.
- Potencialmente el mejor rendimiento sobre los documentos del corpus.

**En contra**
- **Barrera de datos insalvable**: como encargado del tratamiento, el middleware **no puede reutilizar datos de un cliente para entrenar modelos** salvo instrucción o acuerdo expreso; hacerlo lo reclasificaría como corresponsable bajo el art. 26 del GDPR ([ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md)). Sin corpus, no hay entrenamiento.
- Plazos y coste incompatibles con el alcance de la entrega.
- Añadir un país exige recolectar corpus y reentrenar: la opción que **peor** escala en el eje que importa.
- Obliga a asumir con recursos propios el análisis de sesgo demográfico y la validación del modelo.

### Opción D — OCR genérico más LLM multimodal

Pipeline en dos etapas: OCR genérico que devuelve texto con **geometría normalizada** y, sobre esa salida más la imagen, un LLM multimodal que extrae campos contra un **esquema estricto** definido por país y documento como dato.

**A favor**
- **Cobertura por instrucción, no por entrenamiento**: añadir un documento es escribir una plantilla versionada.
- **Elimina la brecha de paridad multinube**: Claude está en Bedrock y en Agent Platform, y el OCR genérico existe en ambas con precios comparables.
- Robusto ante variación de calidad, perspectiva e iluminación, que es donde fallan las reglas posicionales.
- El esquema estricto convierte una respuesta mal formada en error detectable (`ProviderContractViolation`) en lugar de en un dato incorrecto que avanza en silencio.
- Se combina con verificación determinista: la MRZ se valida con `MrzPort` conforme a ICAO Doc 9303, sin delegarla al modelo.

**En contra**
- **No determinista**: hay que fijar parámetros de generación, versionar modelo y prompt, y conservar el resultado como evidencia.
- Coste por documento superior, con componente variable difícil de acotar.
- **Superficie de inyección de prompt desde el documento**, que puede contener texto diseñado para alterar la instrucción.
- Latencia mayor y dependencia de un servicio de inferencia con sus cuotas y modos de fallo.
- El prompt caching **no es ahorro garantizado**: con TTL de 5 minutos —o 1 hora opcional en algunos modelos—, mínimos de 1.024 a 4.096 tokens por checkpoint y máximo de 4 checkpoints por petición, en un tenant de bajo volumen puede ser **neto negativo** por el sobrecoste de escritura.

## Decisión

**Se adopta la opción D. Se descartan `AnalyzeID` y los procesadores de identidad de Document AI.**

El argumento decisivo es de cobertura: los servicios gestionados **no cubren el mercado del producto**, y su cobertura depende del roadmap de un tercero. El de refuerzo es arquitectónico: este patrón convierte una brecha de paridad en una no-brecha, porque el componente que hace el trabajo difícil está disponible en las dos nubes.

La opción B se descarta como estrategia principal, aunque sus técnicas se conservan como preprocesamiento: la rectificación de perspectiva y el recorte mejoran la entrada de las etapas siguientes.

Cuatro controles atacan las debilidades de la decisión:

1. **La MRZ no la interpreta el modelo.** Se decodifica y verifica con `MrzPort`, incluidos los dígitos de control. Cuando el documento tiene MRZ, es la fuente autoritativa y la salida del LLM se contrasta contra ella.
2. **Esquema de salida estricto y validación obligatoria.** Toda respuesta que no valide es `ProviderContractViolation`, nunca un dato aceptado con confianza baja.
3. **Mitigación de inyección de prompt**: separación entre instrucción y contenido, texto extraído tratado como dato no confiable, y validación de que los campos proceden de la imagen ([08 §8](../08-ia-y-extraccion-semantica.md)).
4. **Evidencia de reproducibilidad**: se registran modelo, versión, plantilla, parámetros de generación y umbrales, de modo que el resultado sea explicable aunque no sea reproducible bit a bit.

Sobre el prompt caching, **se evalúa por tenant y no se presupone**. Las cifras de «hasta 90 %» son reducción de **coste**, no de tokens —los tokens se siguen contando y se facturan con descuento—, y «hasta 85 %» de latencia es un techo de marketing.

## Consecuencias

### Positivas

- Cobertura de documentos de LATAM y UE sin depender del roadmap de un proveedor de nube.
- Un documento nuevo entra en producción como dato versionado, no como despliegue.
- `DocumentOcrPort` y `LlmPort` se portan con riesgo bajo y muy bajo respectivamente.
- LLM y verificación determinista de MRZ dan defensa en profundidad: dos mecanismos independientes que deben coincidir.

### Negativas

- Coste por documento superior al de un procesador gestionado, con componente variable.
- No determinismo, que obliga a conservar evidencia y a versionar prompt y modelo como si fueran código.
- Superficie de ataque nueva: inyección de prompt desde el contenido del documento.
- Dependencia de un proveedor de modelos en el camino crítico, y calidad por país que hay que medir con conjunto dorado propio.

### Neutras

- El OCR genérico se contrata en la nube de despliegue, con precios comparables.
- La plantilla de extracción por país y documento sigue el ciclo de vida y el versionado inmutable de [ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md).
- Los artefactos de imagen viajan como punteros, nunca como contenido en el estado del orquestador ([ADR-0011](0011-punteros-a-objetos-en-lugar-de-payloads.md)).

## Criterios de revisión

- **Si `AnalyzeID` o Document AI amplían su cobertura a los documentos del alcance** con calidad verificada sobre el conjunto dorado propio, procede reevaluarlos como proveedor primario con el LLM como respaldo.
- **Si el coste por sesión del LLM supera el presupuesto** de un segmento, la respuesta es reducir el trabajo del modelo —más preprocesamiento determinista, más uso de MRZ— antes que volver a plantillas posicionales.
- **Si `ProviderContractViolation` o la derivación a revisión humana se desvían** más allá de los umbrales de reversión canaria, la versión de prompt o de modelo se revierte.
- **Si se confirma un incidente de inyección de prompt desde documento**, hay que endurecer la separación entre instrucción y contenido antes de ampliar cobertura.
- **Si el proveedor de LLM deja de estar disponible en una de las dos nubes**, la premisa de paridad desaparece y hay que reevaluar el patrón completo.

## Referencias

- [gcp-paridad-de-servicios §3, brecha 8 — cobertura de documentos no estadounidenses](../referencias/gcp-paridad-de-servicios.md)
- [gcp-paridad-de-servicios §2, capacidades 8 y 9](../referencias/gcp-paridad-de-servicios.md)
- [aws-arquitecturas-de-referencia — verificación de cifras, punto 3](../referencias/aws-arquitecturas-de-referencia.md)
- [Prompt caching for faster model inference — Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [cumplimiento-normativo-y-estandares §A.1 — ICAO Doc 9303, dígitos de control](../referencias/cumplimiento-normativo-y-estandares.md)
- [08 — IA y extracción semántica §1, §5 y §8](../08-ia-y-extraccion-semantica.md)
