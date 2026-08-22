# ADR-0003 — Python 3.12 como runtime principal del núcleo y de los adaptadores

| Campo | Valor |
|---|---|
| Estado | **Superada por [ADR-0016](0016-python-314-como-runtime-principal.md)** |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [ADR-0008](0008-ocr-generico-mas-llm-en-lugar-de-analyzeid.md) · [08 — IA y extracción semántica](../08-ia-y-extraccion-semantica.md) · [09 — Biometría y liveness](../09-biometria-y-liveness.md) · [18 — Desarrollo local](../18-desarrollo-local.md) |

> **Este ADR fue superado el 2026-08-22 por [ADR-0016](0016-python-314-como-runtime-principal.md).**
> Su decisión sobre el **lenguaje** sigue vigente y ADR-0016 la mantiene sin cambios: el núcleo
> y los adaptadores siguen siendo Python por las razones que se argumentan aquí. Lo único que
> ADR-0016 cambia es la **versión**, de 3.12 a 3.14. Se conserva este documento porque el
> razonamiento sobre el lenguaje, las opciones descartadas y la refutación de las cifras del
> spec original siguen siendo la referencia.

## Contexto

El middleware ejecuta tres clases de trabajo con perfiles distintos:

1. **Orquestación y lógica de negocio.** Resolver la especificación del tenant, invocar puertos, componer evidencia, aplicar umbrales. Ligado a entrada/salida.
2. **Procesamiento de imagen de documento.** Rectificación de perspectiva, recorte, mejora de contraste, decodificación de MRZ, detección de manipulación. Ligado a CPU, con dependencia fuerte de bibliotecas nativas.
3. **Inferencia de modelos.** Extracción de *embeddings* faciales para el cotejo 1:1 del adaptador GCP de `FaceMatchPort`, que en AWS se resuelve con Rekognition pero en GCP exige ejecutar ONNX en Cloud Run.

El tercer punto no es accesorio: es una de las brechas de paridad. Si en GCP no se puede ejecutar un modelo de *embeddings* faciales en proceso, `FaceMatchPort` se queda sin adaptador.

Conviene descartar un falso condicionante del spec original: la supuesta necesidad de fijar Lambda en 3.008 MB «para AVX-512». Es doblemente incorrecta. El rango real es **128 MB a 10.240 MB en incrementos de 1 MB** —3.008 MB fue el máximo hasta diciembre de 2020— y la documentación de Lambda cubre **AVX2**, no AVX-512, sin restricción de memoria asociada; `arm64` usa NEON y no soporta AVX2. El dimensionado se hace por perfil de rendimiento medido, no por un límite inexistente.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Ejecutar ONNX y visión artificial en proceso | Exige ecosistema maduro de *bindings* nativos y modelos preentrenados |
| Arranque en frío en un plano serverless | Penaliza imágenes grandes y inicialización lenta |
| Núcleo con `mypy` estricto | Exige un sistema de tipos utilizable en un lenguaje dinámico |
| Concurrencia por instancia en Cloud Run (hasta 1.000) | El GIL y el estado implícito por hilo se vuelven riesgos reales |
| Un lenguaje frente a políglota por servicio | Menos superficie operativa frente a mejor herramienta por problema |
| Disponibilidad de perfiles | Determina la velocidad real del equipo |

## Opciones consideradas

### Opción A — TypeScript en Node.js, con servicios políglotas donde haga falta

Núcleo y adaptadores en TypeScript; visión artificial e inferencia en servicios Python separados.

**A favor**
- Sistema de tipos estructural comprobado en compilación, más expresivo que las anotaciones de Python.
- Arranque en frío muy competitivo en el plano de control, con modelo asíncrono maduro y sin GIL en la ruta de entrada/salida.
- Podría compartirse con la consola de revisión humana ([ADR-0010](0010-revision-humana-construida-a-medida.md)).

**En contra**
- **Bloqueante criptográfico verificado:** Tink no tiene versión JavaScript/TypeScript mantenida. En GCP, donde no existe el AWS Database Encryption SDK, el cifrado por tenant es el control primario de aislamiento ([ADR-0005](0005-aislamiento-multitenant-en-capas.md)); en Node.js habría que implementarlo contra la API de Cloud KMS o desplegar un *sidecar* en Go o Java. La opción «un solo lenguaje» se vuelve políglota por obligación.
- El ecosistema de visión artificial en servidor es marginal: `onnxruntime-node` existe, pero el preprocesamiento vive en OpenCV, NumPy y Pillow, sin equivalentes de calidad comparable.
- La partición políglota duplica cadenas de compilación y despliegue, y añade un salto de red en el camino crítico.

### Opción B — Go

Todo el sistema en Go, con ONNX Runtime vía cgo.

**A favor**
- Arranques en frío mínimos, binario único, huella de memoria baja: el mejor ajuste puro a serverless.
- Concurrencia real sin GIL, adecuada a la alta concurrencia por instancia de Cloud Run.
- Tipado estático fuerte y **Tink sí tiene implementación en Go**, de modo que la capa criptográfica de GCP queda cubierta sin *sidecar*.

**En contra**
- **El ecosistema de visión artificial e inferencia es el punto débil.** Los *bindings* de ONNX Runtime dependen de cgo, lo que anula buena parte de la ventaja de despliegue, y no hay equivalentes maduros a OpenCV y NumPy.
- La evaluación de modelos —conjuntos dorados, métricas de extracción, análisis de sesgo, calibración de umbrales— se hace en el ecosistema científico de Python: habría que reimplementarla o mantener un segundo lenguaje solo para eso.
- Verbosidad en la capa de traducción de adaptadores, que es una parte grande del código.
- Menor disponibilidad de perfiles con experiencia en Go y verificación de identidad a la vez.

### Opción C — Python 3.12 en todo el sistema

Un solo lenguaje para núcleo, adaptadores, visión artificial e inferencia. `pyproject.toml` con extras por nube (`[aws]`, `[gcp]`, `[cv]`), `ruff` para lint y formato, `mypy` estricto sobre `domain`, `ports`, `composer`, `application` y `crypto`.

**A favor**
- **El ecosistema de visión artificial y ONNX es el argumento decisivo**: `onnxruntime`, OpenCV, NumPy, Pillow y las bibliotecas de *embeddings* faciales son de primera clase aquí y de segunda o inexistentes en las alternativas. La brecha de `FaceMatchPort` en GCP se cierra sin salir del lenguaje.
- Tink tiene implementación en Python, y los SDK de ambas nubes son de primera clase, incluido el AWS Database Encryption SDK.
- Continuidad entre código de producción y de evaluación: umbrales calibrados una sola vez.
- Los extras evitan que la imagen del plano de control arrastre la pila de visión.
- 3.12 aporta sintaxis nativa de genéricos y `TypeAliasType` para modelar identificadores de dominio sin `NewType` en todas partes.

**En contra**
- Tipado gradual: los adaptadores que hablan con SDK de terceros conviven con `Any` en los bordes.
- **El GIL es un riesgo real en Cloud Run**, con hasta 1.000 peticiones concurrentes por instancia. Obliga a dimensionar por concurrencia medida y a evitar todo estado implícito por hilo.
- La imagen con la pila de visión es pesada, lo que empeora el arranque en frío.
- Rendimiento bruto inferior cuando el preprocesamiento no se delega a bibliotecas nativas.

## Decisión

**Se adopta Python 3.12 como runtime principal**, con el código compatible con 3.11 para que las pruebas corran en el entorno de construcción.

El argumento decisivo es **el ecosistema de visión artificial y ONNX**. Una de las brechas de paridad —`FaceMatchPort` en GCP, sin Rekognition— se resuelve ejecutando un modelo ONNX en proceso, y ese trabajo solo es de primera clase en Python. Elegir TypeScript o Go obligaría a un servicio Python separado precisamente para la parte más delicada del sistema: se pagaría el coste de ser políglota **sin** obtener la ventaja de un lenguaje único. El segundo argumento, coincidente, es criptográfico: Tink en Python cubre el adaptador GCP sin *sidecar*.

Las debilidades se gestionan con reglas explícitas: **`mypy` estricto** en el núcleo, con la frontera hacia los adaptadores deliberada y documentada; **nada de estado implícito por hilo**, con el `TenantContext` pasado como parámetro; **extras opcionales**, de modo que el plano de control no instale `[cv]`; y **dimensionado por medición** dentro del rango real de Lambda, sin asumir AVX-512 sin verificación en tiempo de ejecución.

## Consecuencias

### Positivas

- Un solo lenguaje, una cadena de herramientas y un conjunto de pruebas para todo el sistema.
- El código de evaluación y el de producción comparten tipos: los umbrales calibrados son los que se aplican.
- Adaptadores de ambas nubes y del proveedor de LLM escritos contra SDK de primera clase.
- El adaptador local del catálogo de puertos es trivial, lo que mantiene el núcleo probable sin nube.

### Negativas

- Arranque en frío superior al de Go donde se carga la pila de visión; se mitiga con imágenes de contenedor y concurrencia aprovisionada.
- El GIL obliga a dimensionar Cloud Run por concurrencia medida y limita el paralelismo intra-instancia.
- Los bordes de adaptador conviven con tipado débil.
- La imagen con `[cv]` es grande y exige análisis continuo de vulnerabilidades.

### Neutras

- Identificadores, archivos, ramas y commits en inglés; documentación y comentarios en español latinoamericano.
- `ruff` cubre lint y formato, sustituyendo la combinación habitual de varias herramientas.

## Criterios de revisión

- **Si el modo sin GIL de CPython alcanza soporte productivo** en ambos runtimes gestionados y las dependencias nativas lo soportan, procede reevaluar el modelo de concurrencia y el dimensionado.
- **Si el arranque en frío del plano de control incumple el SLA** en percentil 99 durante dos trimestres, procede reescribir **solo** el plano de control en un runtime más rápido, asumiendo un poliglotismo acotado.
- **Si aparece Tink mantenido en TypeScript y un ecosistema ONNX comparable en Node.js**, el argumento principal se debilita.
- **Si `FaceMatchPort` deja de necesitar inferencia propia** —por ejemplo, si GCP publica cotejo facial 1:1 apto para uso regulado—, el lenguaje pasa a decidirse por criterios de plano de control.

## Referencias

- [Lambda quotas — memoria 128 MB a 10.240 MB](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [Using AVX2 vectorization in Lambda](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-avx2.html)
- [aws-arquitecturas-de-referencia — verificación de cifras, punto 4](../referencias/aws-arquitecturas-de-referencia.md)
- [gcp-paridad-de-servicios §3, brecha 4 — Tink sin versión JS/TS mantenida](../referencias/gcp-paridad-de-servicios.md)
- [Cloud Run quotas and limits](https://docs.cloud.google.com/run/quotas)
- [20 — Fe de erratas del spec original](../20-fe-de-erratas-del-spec-original.md)
