# 20 — Fe de erratas del spec original

| Campo | Valor |
|---|---|
| **Estado** | Aprobado |
| **Versión** | 1.1.0 |
| **Última actualización** | 2026-08-21 |
| **Responsable** | Arquitectura de la plataforma |
| **Audiencia** | Arquitectura, producto, cliente, auditoría |
| **Documentos relacionados** | [00 — Índice](00-indice.md) · todos — este documento es la trazabilidad entre el spec del cliente y lo implementado |

**Resumen ejecutivo.** El documento fuente del cliente circula y contiene ocho afirmaciones que la investigación de agosto de 2026 verificó y encontró incorrectas, mal atribuidas o incompletas. Aquí están las ocho, una por una, con su veredicto, el dato correcto, la fuente que lo respalda, el impacto sobre el diseño y **la redacción que debe usarse en su lugar**. Sirve para dos cosas: justificar por qué el repositorio contradice el spec en esos puntos, y evitar que las afirmaciones erróneas se repitan en propuestas comerciales o en documentación derivada.

---

## 1. Propósito

El documento fuente del cliente (`middlewarespec.md`) contiene ocho afirmaciones que la investigación de referencia de agosto de 2026 **verificó y encontró incorrectas, mal atribuidas o incompletas**. Este documento las recoge una por una con su veredicto, el dato correcto, la fuente y el impacto concreto sobre el diseño.

**Por qué importa este documento:**

1. **Trazabilidad.** Un lector que conozca el spec original debe poder entender por qué el repositorio dice otra cosa, sin sospechar que se ignoró el requisito.
2. **Prevención de regresión.** Un desarrollador que lea el spec meses después podría reintroducir la afirmación errónea. Esta tabla es la defensa.
3. **Honestidad técnica.** Varias de las cifras del spec son citables en material comercial. Usarlas expondría a la organización a una reclamación por afirmaciones no sustentadas.

**Regla de trabajo aplicada en toda la verificación:** la documentación oficial del proveedor prevalece sobre sus blogs en cualquier discrepancia de cuotas. Esta regla no es teórica: uno de los errores documentados aquí proviene de un blog oficial que contradice la cuota publicada.

## 2. Tabla resumen

| # | Afirmación del spec | Veredicto | Impacto en el diseño |
|---|---|---|---|
| 1 | Memoria de Lambda limitada a **3.008 MB** por AVX-512 | ❌ **Doblemente falso** | Alto: capaba rendimiento y CPU sin motivo |
| 2 | Ahorro del **72,5 %** con Express Workflows | ❌ **No confirmado por ninguna fuente** | Medio: la cifra es incitable; el ahorro real es específico de cada flujo |
| 3 | Usar `CachingCryptoMaterialsManager` para lograr **77 %** de ahorro de KMS | ⚠️ **Cifra correcta, atribución peligrosamente errónea** | **Crítico**: implementarlo produce el bug que el artículo describe |
| 4 | Prompt caching: **90 %** de tokens y **85 %** de latencia | ⚠️ **Mal formulado; son techos de marketing** | Medio: afecta al dimensionado y puede ser neto negativo |
| 5 | Step Functions Standard **sin límite** de duración | ⚠️ **Impreciso; y el spec omitía un límite real** | Alto: el límite omitido de 25.000 eventos aborta ejecuciones |
| 6 | Usar los procesadores de identidad gestionados para extracción documental | ❌ **Cubren esencialmente EE. UU.** | **Crítico**: inviable para LATAM y Europa |
| 7 | Usar el servicio gestionado de revisión humana | ❌ **Cerrado a nuevos clientes; los equivalentes están apagados** | Alto: obliga a construir el componente |
| 8 | Componentes OSS del ecosistema utilizables sin más | ❌ **Varios con licencias incompatibles o inexistentes** | **Crítico**: riesgo legal no técnico |

### 2.1 Redacción correcta que debe usarse en su lugar

Esta es la parte operativa del documento. El spec original circula: aparece en propuestas, en presentaciones y en documentación derivada. Cuando haya que sustituir una de sus afirmaciones, **use estas formulaciones literalmente**; están redactadas para ser defendibles ante un arquitecto que verifique la fuente.

| # | En vez de decir… | Diga… |
|---|---|---|
| **E-01** | *"Las funciones se configuran con 3.008 MB, el máximo de Lambda, para disponer de AVX-512."* | *"La memoria se dimensiona por perfil de rendimiento medido, dentro del rango real de 128 MB a 10.240 MB. La documentación de la plataforma cubre AVX2, no AVX-512, y no existe ningún requisito de memoria ligado a extensiones vectoriales; `arm64` usa NEON."* |
| **E-02** | *"El patrón anidado con Express Workflows ahorra un 72,5 %."* | *"El ahorro depende del número de transiciones y de la duración media de cada flujo, y se calcula por flujo con la fórmula de [07 §2.1](07-orquestacion.md). Las cifras publicadas por el proveedor son del 98 % para Express puro y de aproximadamente el 52 % para el patrón anidado, sobre un ejemplo concreto."* |
| **E-03** | *"Se usa `CachingCryptoMaterialsManager` para lograr un 77 % de ahorro en llamadas al servicio de claves."* | *"Se usa el **hierarchical keyring**, que es la recomendación del proveedor. El `CachingCryptoMaterialsManager` es precisamente el componente que causa el problema de estampida de caché descrito en el caso publicado; la reducción del 77 % es real, pero no se obtuvo con él."* |
| **E-04** | *"El prompt caching reduce los tokens un 90 % y la latencia un 85 %."* | *"El prompt caching reduce el **coste** de los tokens cacheados —que se siguen contando y se facturan con descuento—, con techos publicados de hasta el 90 % en coste y el 85 % en latencia que son valores máximos de marketing, no esperados. Hay mínimos por punto de caché, un máximo de cuatro puntos por petición y un TTL de 5 minutos, ampliable a 1 hora en algunos modelos. **En tenants de bajo volumen el resultado puede ser neto negativo.**"* |
| **E-05** | *"Las ejecuciones Standard no tienen límite de duración."* | *"Las ejecuciones Standard duran hasta **un año**, conservan historial **90 días** tras el cierre, admiten un payload de **256 KiB** y están limitadas a **25 000 eventos de historial por ejecución** — este último es el límite que de verdad aborta ejecuciones largas y exige el patrón de continuación."* |
| **E-06** | *"La extracción de campos del documento se resuelve con el procesador de identidad gestionado."* | *"Los procesadores de identidad gestionados de ambas nubes cubren esencialmente documentos de Estados Unidos y no sirven para LATAM ni para Europa. El patrón portable es **OCR genérico más un LLM multimodal** con plantilla por país y tipo de documento."* |
| **E-07** | *"La revisión humana se apoya en el servicio gestionado de la nube."* | *"El servicio gestionado de revisión humana de AWS **está cerrado a nuevos clientes** y los equivalentes de GCP **están apagados**. La revisión humana se construye a medida en ambas nubes, lo que además elimina la asimetría entre ellas y permite el registro inmutable de decisiones que el cumplimiento exige."* |
| **E-08** | *"Se reutilizan componentes open source del ecosistema de eKYC."* | *"Cada componente se evalúa por su licencia verificada antes de incorporarlo. Varios de los citados en el spec son inutilizables en un producto propietario expuesto por red: copyleft de red, ausencia de licencia —que equivale a todos los derechos reservados—, licencia contradictoria, o licencia que prohíbe expresamente ofrecer el software como servicio gestionado. Y la licencia de los **pesos de un modelo** es independiente de la de su código."* |

## 3. Detalle por errata

---

### E-01 — Memoria de Lambda de 3.008 MB por requisito de AVX-512

| Campo | Contenido |
|---|---|
| **Afirmación original** | Las funciones deben configurarse con 3.008 MB de memoria, que es el límite de Lambda, para disponer de AVX-512 |
| **Veredicto** | ❌ **CONTRADICHO — doblemente incorrecto** |
| **Dato correcto (a)** | El rango real de memoria es de **128 MB a 10.240 MB en incrementos de 1 MB**. La cifra de 3.008 MB fue el máximo histórico **hasta diciembre de 2020**: lleva más de cinco años obsoleta |
| **Dato correcto (b)** | **No existe ningún requisito de memoria vinculado a AVX-512.** La documentación de Lambda cubre **AVX2** —extensión de vectorización del conjunto de instrucciones x86 que opera sobre vectores de 256 bits— y **no menciona AVX-512 en absoluto**, ni ninguna restricción de tamaño de memoria asociada a extensiones vectoriales. Además, `arm64` usa NEON y **no soporta las extensiones AVX2 de x86**; el uso de AVX2 no tiene coste adicional |
| **Fuente** | Documentación oficial de cuotas de Lambda y de vectorización AVX2 |
| **Por qué apareció el error** | La afirmación fusiona dos datos no relacionados y desactualizados |

**Impacto en el diseño:**

- Fijar 3.008 MB como límite **capa también la CPU disponible**, porque en Lambda la asignación de vCPU es proporcional a la memoria. Habría degradado precisamente el worker de cotejo facial, que es el que más se beneficia de CPU alta.
- El repositorio **dimensiona por perfil de rendimiento medido**, no por límites inexistentes ([16](16-guia-de-despliegue-aws.md) §4.5).
- Si en algún momento se dependiera de aceleración vectorial: fijar arquitectura `x86_64` explícitamente si se requiere AVX2, **no asumir disponibilidad de AVX-512** sin verificación en tiempo de ejecución, y medir.

> **Nunca repita la afirmación "3008 MB para AVX-512".**

**Cuotas reales verificadas de Lambda:**

| Cuota | Valor |
|---|---|
| Memoria de función | **128 MB – 10.240 MB**, incrementos de 1 MB |
| Timeout máximo | 900 s (15 min) |
| Almacenamiento efímero | 512 MB – 10.240 MB |
| Paquete comprimido | 50 MB |
| Paquete descomprimido (con capas) | 250 MB |
| Imagen de contenedor descomprimida | 10 GB |
| Payload síncrono / asíncrono | 6 MB / 1 MB |
| Concurrencia por defecto | 1.000 por región |
| *Burst* de concurrencia | 1.000 entornos cada 10 s por función |

---

### E-02 — Ahorro del 72,5 % con Express Workflows

| Campo | Contenido |
|---|---|
| **Afirmación original** | El uso de Express Workflows produce un ahorro del 72,5 % |
| **Veredicto** | ❌ **NO CONFIRMADO — la cifra no aparece en ninguna fuente** |
| **Datos correctos** | Sobre un flujo de ejemplo ejecutado 1.000 veces: **Standard puro** con 17 transiciones = **0,42 USD**; **Express puro** con duración media de 11.300 ms = **0,01 USD** (**98 %** de reducción); **anidado** con padre Standard de 8 transiciones e hijo Express = **0,20 USD** (**~52 %** de reducción) |
| **Fuente** | Blog de ingeniería del proveedor, con el cálculo desglosado |
| **Hipótesis del origen** | 72,5 % podría ser un promedio, una interpolación entre ambos escenarios, o una cifra de otra fuente no citada |

**Impacto en el diseño:**

- **Cualquier porcentaje de ahorro es totalmente dependiente del flujo concreto**: de su número de transiciones y de su duración media. El propio ejemplo lo demuestra: el ahorro cae del 98 % al 52 % solo por conservar 8 transiciones Standard en el padre.
- El repositorio **calcula el coste esperado por flujo** con las transiciones reales, en el compilador ([04](04-motor-de-composicion.md) §7.1).
- Y **no adopta Express puro**, que es el escenario del 98 %: Express es at-least-once, dura 5 minutos, y no soporta `.waitForTaskToken`, `.sync`, Distributed Map ni Activities. El flujo de onboarding necesita esperas largas y exactly-once ([07](07-orquestacion.md) §2.2).
- Dato adicional útil: **arrancar un workflow anidado no tiene coste adicional**.

---

### E-03 — CCMM y el 77 % de ahorro de KMS

| Campo | Contenido |
|---|---|
| **Afirmación original** | Usar `CachingCryptoMaterialsManager` para lograr un 77 % de ahorro en costes de KMS |
| **Veredicto** | ⚠️ **CIFRA CORRECTA, ATRIBUCIÓN PELIGROSAMENTE ERRÓNEA** |
| **Qué es cierto** | La reducción del **77 %** del coste de KMS es real y está documentada en un caso de estudio |
| **Qué es falso, y es lo grave** | **No se logró con el CCMM.** El artículo describe al CCMM como **la causa del problema**: en entornos multihilo, cuando expira una entrada de caché de clave de datos, **no hay coordinación entre hilos** y N hilos llaman a `GenerateDataKey` de forma independiente, generando **N claves de datos distintas** |
| **El daño completo** | No se limita al pico de llamadas: las claves cifradas excedentes **degradan el ratio de aciertos del lado del descifrado**, provocando llamadas redundantes adicionales de forma sostenida. En el caso documentado, esto produjo un **30 % de claves de datos únicas por registro** y **millones de llamadas duplicadas por hora** |
| **Cómo se logró realmente el 77 %** | Con un cliente decorado que usa cachés con **carga atómica**: exactamente un hilo ejecuta la llamada real mientras los demás bloquean y esperan ese único resultado — precisamente lo que el CCMM no garantiza |
| **Recomendación oficial del proveedor** | **Hierarchical keyring**, con branch keys persistidas y una caché diseñada para entornos multihilo, con ventana de notificación de pre-expiración de **10 segundos** |

**Impacto en el diseño — el más grave de las ocho erratas:**

> **Si el spec dice "usar CCMM para lograr 77 % de ahorro", el equipo implementará exactamente lo que el artículo identifica como el bug.** No es un error de documentación: es una instrucción que produce el fallo.

- El repositorio adopta el **hierarchical keyring** como ruta por defecto, que además es la primitiva que exige la biblioteca de cifrado de base de datos: una sola decisión cubre el problema de escala y el requisito de búsqueda sobre campos cifrados.
- Donde no es aplicable (adaptadores propios, GCP), se implementa **caché con carga atómica explícita**.
- Se instrumenta `crypto.unique_data_keys_ratio` con alarma por encima de 0,05 — el caso patológico documentado alcanzó **0,30**.
- El escenario de carga C-4 (estampida criptográfica) es **obligatorio antes de cada promoción mayor**.

**Redacción correcta:** *"Evitar el CCMM en entornos concurrentes; usar hierarchical keyring (recomendación oficial) o caché con carga atómica. El caso documentado reporta un 77 % de reducción de coste de KMS con este último enfoque."*

Ver [06 — Criptografía](06-criptografia-y-gestion-de-claves.md) §5.

---

### E-04 — Prompt caching: 90 % de tokens y 85 % de latencia

| Campo | Contenido |
|---|---|
| **Afirmación original** | El prompt caching reduce un 90 % los tokens y un 85 % la latencia |
| **Veredicto** | ⚠️ **PARCIAL Y MAL FORMULADO** |
| **Corrección 1** | **El 90 % es reducción de *coste*, no de *tokens*.** El número de tokens de entrada **no baja**: los tokens cacheados se facturan con descuento. La distinción importa para el dimensionado de cuotas y de límites de contexto, **que no mejoran** |
| **Corrección 2** | **"Hasta" no es un valor esperado.** Ambos porcentajes son techos alcanzables solo con reutilización de prefijo casi perfecta |
| **Corrección 3** | **La documentación oficial no da porcentajes.** Describe la funcionalidad como orientada a reducir latencia y coste de tokens de entrada. Los porcentajes proceden de material de marketing |

**Restricciones operativas que determinan si el ahorro es siquiera alcanzable:**

| Parámetro | Valor |
|---|---|
| Mínimo de tokens por punto de caché | **512 a 4.096 según el modelo** |
| Máximo de puntos de caché por petición | **4** |
| TTL por defecto | **5 minutos** |
| TTL extendido | **1 hora** (opcional, en modelos que lo soportan) |
| Multiplicador de escritura, 5 min | **1,25×** |
| Multiplicador de escritura, 1 h | **2,0×** |
| Multiplicador de lectura | **0,1×** |

**Impacto en el diseño:**

- Con TTL de 5 minutos y mínimos de miles de tokens, el ahorro **solo se materializa** si se mantiene un prefijo de prompt estable y voluminoso **y** hay frecuencia de invocación suficiente para que la caché no expire entre peticiones.
- **En un tenant de bajo volumen, el prompt caching puede ser neto negativo** por el sobrecoste de escritura. Y la larga cola de países con una sesión por hora es precisamente donde este producto quiere competir.
- Por eso el repositorio **activa el caché por (tenant, plantilla)** en función de la tasa observada de invocación, mediante un proceso que observa la métrica, y no con una configuración global fija ([08](08-ia-y-extraccion-semantica.md) §5.3).
- El prefijo del prompt está estructurado en capas precisamente para maximizar la parte estable y cacheable ([08](08-ia-y-extraccion-semantica.md) §4.1).

---

### E-05 — Duración de Standard Workflows y el límite omitido

| Campo | Contenido |
|---|---|
| **Afirmación original** | Standard Workflows no tiene límite de duración |
| **Veredicto** | ⚠️ **IMPRECISO — y el spec omitía un límite real y relevante** |
| **Dato correcto (duración)** | La duración máxima de Standard es de **1 año**; la de Express, de **5 minutos**. La afirmación de "sin límite" proviene de un **blog oficial del propio proveedor** que contradice su documentación de cuotas |
| **Dato correcto (retención)** | El historial de Standard se retiene **90 días** tras el cierre de la ejecución, reducible a 30 por solicitud de soporte. Confirmado, y el spec lo recogía bien |
| **Dato omitido — el importante** | **El tamaño máximo de historial es de 25.000 eventos por ejecución.** El spec no lo mencionaba. Es una restricción real que se alcanza en eKYC con reintentos multiplicados o con bucles sobre N documentos, y **aborta la ejecución** |
| **Dato omitido adicional** | El payload de entrada y salida está limitado a **256 KiB**, y la definición de la máquina de estados a **1 MB** (cuota **dura**) |

**Impacto en el diseño:**

- **Alcanzar el límite de historial aborta la ejecución.** Para una sesión en revisión humana con días de trabajo invertido, es una pérdida inaceptable.
- El repositorio adopta el patrón oficial de **arrancar ejecuciones nuevas** para evitar la cuota: el compilador estima la cota superior de eventos y advierte al superar el 60 % del límite ([07](07-orquestacion.md) §7).
- La **sesión, no la ejecución, es la unidad de negocio**: mantiene una lista de las ejecuciones que la componen, y la continuación es transparente para el requirente.
- **La retención de 90 días es insuficiente para trazabilidad KYC/AML**, que exige de 5 a 10 años. Por eso el expediente regulatorio vive en el log de auditoría y en las evidencias selladas en almacenamiento WORM, no en el historial del orquestador. El historial de los hijos Express, además, **solo existe en los registros de log** con su propia política y coste.

**Lección transversal:** *la documentación oficial prevalece sobre los blogs del propio proveedor en cualquier discrepancia de cuotas.*

---

### E-06 — Procesadores de identidad gestionados

| Campo | Contenido |
|---|---|
| **Afirmación original** | Usar los servicios gestionados de análisis de documentos de identidad para la extracción estructurada |
| **Veredicto** | ❌ **CONTRADICHO — cubren esencialmente Estados Unidos** |
| **Datos correctos** | El servicio de análisis de identidad de AWS cubre documentos de EE. UU. (licencias y pasaportes). En GCP: el analizador de licencias cubre **solo los 50 estados + D.C.**; el de pasaportes, solo EE. UU.; el de verificación de documento de identidad, **solo pasaportes, *passcards* y licencias de EE. UU.** |
| **Dato adicional** | Procesadores de identidad heredados —incluido el de licencia de conducir francesa— se apagaron el **30 de junio de 2026**. Que se retire el procesador de un país europeo señala dónde está la inversión, y no es en la cobertura por país |

**Impacto en el diseño:**

- **Hay paridad en la limitación**: ambas nubes están igual de restringidas. Pero si el producto opera en LATAM, Europa o Asia, **ninguno de los dos sirve**.
- El patrón adoptado es **OCR genérico + LLM multimodal** para la extracción estructurada por país ([08](08-ia-y-extraccion-semantica.md) §2).
- Efecto colateral positivo: este patrón **elimina la brecha de portabilidad**, porque el componente diferenciador —el modelo de lenguaje— tiene paridad casi total entre nubes.
- El repositorio **prohíbe explícitamente** el uso de los procesadores de identidad gestionados en las especificaciones, y el validador rechaza una especificación que declare un proveedor cuya aplicabilidad no cubra los países de la resolución ([04](04-motor-de-composicion.md) §6, comprobación V3).

---

### E-07 — Revisión humana gestionada

| Campo | Contenido |
|---|---|
| **Afirmación original** | Usar el servicio gestionado de revisión humana aumentada |
| **Veredicto** | ❌ **CONTRADICHO — cerrado a nuevos clientes; los equivalentes están apagados** |
| **Dato correcto (AWS)** | Cita textual de su documentación: *"Amazon SageMaker A2I is no longer open to new customers. Existing customers can continue to use the service as normal. AWS continues to invest in security and availability improvements for A2I, but we do not plan to introduce new features."* |
| **Dato correcto (GCP)** | Peor: la revisión humana de Document AI *"is deprecated and will no longer be available on Google Cloud after January 16, 2025"*, y el servicio de etiquetado de datos está **apagado desde el 3 de octubre de 2024**. La recomendación oficial es contratar un partner certificado |

**Impacto en el diseño:**

- **Si el proyecto es nuevo, ni siquiera puede darse de alta** en el servicio de AWS. Esto invierte la premisa: no es que una nube vaya por detrás, es que **ambas han abandonado la revisión humana gestionada**.
- El repositorio construye el `HumanReviewPort` a medida **en ambas nubes**, lo que **elimina la asimetría** en lugar de gestionarla ([02](02-arquitectura.md) §8, decisión A8).
- Ventaja de construirlo: el servicio gestionado nunca dio bien la trazabilidad regulatoria, porque su modelo de plantillas de tarea está pensado para etiquetado de aprendizaje automático, no para decisiones de cumplimiento. Un servicio propio con log de decisiones en almacenamiento WORM cumple mejor.

---

### E-08 — Licencias del ecosistema open source

| Campo | Contenido |
|---|---|
| **Afirmación original** | Los componentes OSS del ecosistema de eKYC son utilizables en el producto |
| **Veredicto** | ❌ **CONTRADICHO — varios tienen licencias incompatibles, inexistentes o contradictorias** |

**Verificación de agosto de 2026:**

| Componente | Licencia real | Consecuencia |
|---|---|---|
| `fastmrz` | **AGPL-3.0** | 🔴 **Copyleft de red**: incompatible con un producto propietario expuesto por red |
| `Laligence-Dev/ekyc-system` | **Sin licencia** | 🔴 Todos los derechos reservados: no hay concesión de uso |
| `YegorCherov/document-scanner` | **Sin licencia** | 🔴 Ídem |
| `OmniMRZ` | **Contradicción**: el archivo LICENSE dice Apache-2.0, el badge del README dice AGPL-3.0 | 🔴 Bloqueado hasta aclaración escrita |
| Backend de **Ballerine** | **Elastic License 2.0 por defecto** | 🔴 **Prohíbe ofrecerlo como servicio gestionado a terceros** — que es el modelo de negocio de este producto |
| `@openeudi/*` | **Apache-2.0** | ✅ Apta |
| `minivision-ai/Silent-Face-Anti-Spoofing` | **Apache-2.0** | ⚠️ Apta por licencia, pero **el modelo es de 2020**: no recomendada para producción regulada |
| `fbieberly/document_warp` | **MIT** | ✅ Apta como código de referencia |
| `joellijo32/Document-Scanner-using-OpenCV` | **MIT** | ✅ Apta como código de referencia |
| `team-idswyft/idswyft-community` | **MIT** | ✅ Apta |

**Y la advertencia que casi nunca se hace:**

> ⚠️ **Varios conjuntos de pesos de modelos arrastran restricciones de uso no comercial INDEPENDIENTES de la licencia del código.** La licencia del repositorio no es la licencia de los pesos. Es el error más caro en proyectos de aprendizaje automático, y el análisis de composición estándar **no lo detecta**, porque los pesos no son un paquete, no aparecen en el manifiesto de dependencias y no tienen metadatos de licencia normalizados.

**Impacto en el diseño:**

- **`mrz.parse.v1` se implementa a mano.** Es la decisión correcta por tres razones independientes: elimina el riesgo de licencia, el algoritmo está completamente especificado en ICAO Doc 9303, y no tiene dependencia de nube ([15](15-catalogo-de-proveedores-y-licencias.md) §3.3).
- **Política de licencias formal** con puerta bloqueante en CI: permitidas MIT, Apache-2.0 y BSD; prohibidas AGPL, GPL enlazada, SSPL, Elastic License, BSL, Commons Clause, licencias no comerciales y ausencia de licencia; con una categoría de revisión legal para LGPL, MPL y similares ([15](15-catalogo-de-proveedores-y-licencias.md) §4).
- **Registro de modelos con verificación separada** de la licencia del código y la de los pesos. Un modelo con licencia de pesos desconocida **no llega a producción** ([15](15-catalogo-de-proveedores-y-licencias.md) §5.3).
- Este riesgo es **legal, no técnico**, y se materializa en una auditoría de *due diligence* — típicamente en el peor momento posible: una ronda de financiación, una adquisición, o un contrato con banca.

## 4. Advertencias transversales sobre la calidad de las fuentes

Cuatro lecciones que la verificación dejó y que se aplican a todo el proyecto:

| # | Lección | Ejemplo concreto |
|---|---|---|
| **L1** | **La documentación oficial prevalece sobre los blogs del propio proveedor** en cualquier discrepancia de cuotas | E-05: un blog oficial afirma "sin límite" contra una cuota publicada de 1 año |
| **L2** | **Los blogs de terceros no son autoritativos para precios ni cuotas** | Los precios de KMS citados en la investigación provienen de un blog y **deben re-verificarse contra la página oficial de precios** antes de entrar en cualquier modelo financiero |
| **L3** | **Los valores numéricos del código de ejemplo son valores de demostración, no recomendaciones** | `length(15)` en un beacon, TTL de 60 s, TTL de caché de 6.000, memoria de 256 MB, TTL de 10 días. Copiarlos a producción sin dimensionar es un error, y **en el caso de la longitud de beacon es un error irreversible** |
| **L4** | **Una cifra sin fuente no entra en un spec** | El 72,5 % de E-02 y los porcentajes de E-04 no provienen de ninguna de las fuentes citadas en el spec original |

## 5. Conflictos de diseño detectados en la verificación

La investigación identificó además tres conflictos entre fuentes que el spec no resolvía y que este repositorio cierra explícitamente:

| # | Conflicto | Resolución adoptada | Documento |
|---|---|---|---|
| **C-1** | **Índice de beacon frente a la restricción de clave de partición**: el aislamiento por IAM exige que todo índice global tenga el tenant en su clave de partición, pero los índices de beacon tienen el beacon como clave | **Campo virtual cuya primera parte es el `tenant_id`**, de modo que el índice sigue siendo tenant-scoped. Beneficio colateral: la población efectiva del beacon es la del tenant, lo que mejora el dimensionado y reduce la fuga | [06](06-criptografia-y-gestion-de-claves.md) §6.4 |
| **C-2** | **Clave de partición sin tenant en el patrón de motor de flujos dinámicos** publicado: rompe el aislamiento por IAM tal como está | Clave de partición **`TENANT#<tid>#RUN#<runId>`** con clave de ordenación `TASK#<taskId>` | [03](03-modelo-de-dominio.md) §4.2 |
| **C-3** | **CCMM como causa frente a como solución** | Ver E-03. Hierarchical keyring, o caché con carga atómica | [06](06-criptografia-y-gestion-de-claves.md) §5 |

Y dos riesgos operativos que la fuente original del patrón no abordaba:

| Riesgo | Tratamiento en este repositorio |
|---|---|
| El **indicador de bloqueo huérfano**: si un ejecutor muere tras marcar la tarea como bloqueada y antes de completarla, queda bloqueada indefinidamente | `lock_expires_at` con marca temporal absoluta, *reaper* programado, heartbeat en pasos largos, y **métrica alertable** ([07](07-orquestacion.md) §6.3) |
| Un **TTL de 10 días** en los ítems de caso, incompatible con obligaciones de retención de 5 a 10 años | El TTL se elimina de los ítems de expediente y se reserva para artefactos efímeros y claves de idempotencia ([12](12-retencion-y-borrado.md) §6.1) |

## 6. Qué hacer si aparece una errata nueva

1. **No la corrija en silencio.** Añádala a este documento con veredicto, dato correcto, fuente e impacto.
2. **Verifique en fuente primaria.** La documentación oficial del proveedor o el texto normativo; nunca un blog ni un resumen.
3. **Si no puede verificarla, márquela** con `<!-- PENDIENTE DE VERIFICAR -->` y añádala al inventario de [11](11-cumplimiento-normativo.md) §8 si es regulatoria, o a las decisiones abiertas de [19](19-roadmap.md) §4 si es técnica.
4. **Evalúe si el diseño ya la incorpora.** Varias de estas erratas tienen impacto estructural, no cosmético.
5. **Si tiene impacto comercial** —una cifra citable en material de venta—, notifíquelo al equipo comercial. Es la categoría de error con consecuencias fuera de ingeniería.

---

## Referencias

- [`docs/referencias/aws-arquitecturas-de-referencia.md`](referencias/aws-arquitecturas-de-referencia.md) — sección de verificación de cifras, con el veredicto de cada afirmación, las cuotas oficiales verificadas de Step Functions, Lambda, KMS y la biblioteca de cifrado de base de datos, y las advertencias transversales sobre calidad de las fuentes.
- [`docs/referencias/gcp-paridad-de-servicios.md`](referencias/gcp-paridad-de-servicios.md) — cobertura geográfica de los procesadores de identidad, estado de los servicios de revisión humana, y ausencia de la biblioteca de cifrado de base de datos.
- `CONTEXTO-AGENTES.md` §8 — verificación de licencias del ecosistema OSS.
- [02 — Arquitectura](02-arquitectura.md) · [03 — Modelo de dominio](03-modelo-de-dominio.md) · [04 — Motor de composición](04-motor-de-composicion.md) · [06 — Criptografía](06-criptografia-y-gestion-de-claves.md) · [07 — Orquestación](07-orquestacion.md) · [08 — IA y extracción semántica](08-ia-y-extraccion-semantica.md) · [12 — Retención y borrado](12-retencion-y-borrado.md) · [15 — Catálogo de proveedores y licencias](15-catalogo-de-proveedores-y-licencias.md) · [16 — Despliegue AWS](16-guia-de-despliegue-aws.md) · [19 — Roadmap](19-roadmap.md)
