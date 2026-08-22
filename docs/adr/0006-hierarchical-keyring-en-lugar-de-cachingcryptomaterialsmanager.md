# ADR-0006 — Hierarchical keyring en lugar de `CachingCryptoMaterialsManager`

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [06 — Criptografía y gestión de claves](../06-criptografia-y-gestion-de-claves.md) · [ADR-0005](0005-aislamiento-multitenant-en-capas.md) · [20 — Fe de erratas](../20-fe-de-erratas-del-spec-original.md) · [10 — Multinube](../10-multicloud-aws-gcp.md) |

## Contexto

[ADR-0005](0005-aislamiento-multitenant-en-capas.md) convierte el cifrado de sobre por tenant en el control primario de aislamiento: **cada lectura o escritura sobre datos de un tenant requiere material criptográfico de ese tenant**. Sin caché, cada operación es una llamada a KMS, y el sistema no es viable ni por latencia ni por coste.

El spec original resolvía esto recomendando el **`CachingCryptoMaterialsManager` (CCMM)** del AWS Encryption SDK, respaldado con una cifra: «reducción del 77 % del coste de KMS». **La cifra es real; la atribución es falsa y peligrosa.**

El caso de estudio citado (NICE Actimize, blog de seguridad de AWS) **describe al CCMM como la causa del problema**. En entornos multihilo, cuando una entrada de caché expira **no hay coordinación entre hilos**: cada uno llama por su cuenta a `GenerateDataKey`, de modo que N hilos crean N claves distintas para el mismo tenant en lugar de que uno genere y los demás esperen.

El daño no se limita al pico. Las claves de datos cifradas excedentes **degradan el ratio de aciertos de la caché del lado del descifrado**, produciendo llamadas redundantes de forma sostenida. En el caso documentado se llegó a un **30 % de claves de datos únicas por registro** y a **millones de llamadas API duplicadas por hora**. El 77 % se obtuvo **sustituyendo el comportamiento del CCMM** por una caché con carga atómica, no usándolo.

El riesgo concreto es de implementación literal: si el spec dice «usar CCMM para lograr 77 % de ahorro», el equipo implementará exactamente lo que la fuente identifica como el bug, creyendo seguir una buena práctica.

El modelo de ejecución cambia la forma del problema:

| Modelo | Forma del *stampede* |
|---|---|
| **Lambda** (una petición por entorno) | El *stampede* intraproceso es menos agudo, pero se sustituye por uno **entre entornos**: N entornos fríos son N llamadas a `GenerateDataKey`. El *burst* es de **1.000 entornos cada 10 segundos por función** |
| **Cloud Run** (hasta 1.000 peticiones concurrentes por instancia) | *Stampede* intraproceso clásico, en su forma más aguda |
| **Contenedor de larga vida** | Idéntico al anterior |

Y hay una restricción de portabilidad: en GCP no existen el AWS Database Encryption SDK ni el hierarchical keyring. **Tink no tiene caché de material criptográfico integrada**, y existe un problema de rendimiento conocido de su Envelope AEAD sobre Cloud KMS por la latencia por operación. Allí la caché no es optimización: es requisito de viabilidad.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Cifrado por tenant como control primario | Material criptográfico requerido en cada operación |
| Cuotas y coste de KMS | Sin caché, latencia y factura hacen inviable el sistema |
| Concurrencia alta | Cualquier caché sin coordinación degenera en *stampede* |
| Claves en claro en memoria durante el TTL | El TTL es un control de seguridad, no de rendimiento |
| Búsqueda sobre campos cifrados | El DB-ESDK exige hierarchical keyring: la elección no es independiente |
| Ausencia de equivalente en GCP | Hay que resolverlo dos veces |

## Opciones consideradas

### Opción A — KMS directo por operación, sin caché

**A favor**
- El modelo más simple y el más fácil de defender: **no hay material de clave en claro persistiendo en memoria**.
- Cada uso queda registrado en CloudTrail o en los *audit logs* de Cloud KMS: trazabilidad de uso de clave inmejorable.
- Sin caché no hay *stampede*, ni TTL, ni invalidación que razonar.

**En contra**
- **Inviable por latencia**: una llamada de red en el camino crítico de cada operación, en un flujo que toca decenas de registros por sesión.
- Consume cuota de KMS de forma proporcional al tráfico; las cuotas compartidas van de **10.000 a 100.000 peticiones por segundo** según la región.
- Coste proporcional al volumen, sin palanca de optimización.

### Opción B — `CachingCryptoMaterialsManager`

**A favor**
- Solución integrada y documentada del SDK: cero código propio, configuración declarativa.
- Aporta límites de seguridad útiles listos para usar: máximo de mensajes y de bytes por clave, además del TTL.
- En cargas monohilo o de baja concurrencia funciona y reduce las llamadas a KMS.

**En contra**
- **Descalificador: no coordina la carga entre hilos.** Al expirar una entrada, N hilos generan N claves. Es el modo de fallo exacto que la fuente documenta.
- El daño es **sostenido**: las claves excedentes degradan permanentemente los aciertos del lado del descifrado.
- Difícil de diagnosticar sin instrumentación específica: el sistema funciona, solo cuesta mucho más.
- No existe en GCP, así que no resuelve ni la mitad del problema.

### Opción C — Hierarchical keyring

**Branch keys** almacenadas en una tabla como claves de envoltura intermedias entre la CMK y las claves de datos.

**A favor**
- **Su caché está diseñada para entornos multihilo**: un hilo refresca mientras los demás siguen usando la entrada aún válida, con una **ventana de pre-expiración de 10 segundos**. Es la coordinación que el CCMM no ofrece.
- Es la **recomendación de AWS** y la primitiva que **exige el DB-ESDK**: una decisión cubre escala y búsqueda sobre atributos cifrados.
- **Mitiga el *stampede* entre entornos de Lambda**: la branch key es compartida y persistente, así que los N entornos fríos leen la misma en lugar de generar N claves.
- Encaja de forma natural con clave por tenant, rotación y destrucción programada.

**En contra**
- Es específico de AWS: **no existe en GCP**.
- Añade una tabla de branch keys que aprovisionar, respaldar y proteger, y que pasa a estar en el camino crítico.
- Más conceptos que entender: CMK, branch key, clave de datos.

### Opción D — Caché propia con carga atómica

Decorador sobre el cliente de KMS con dos cachés de carga —`GenerateDataKey` y `Decrypt`—, refresco tras escritura y **carga atómica**: exactamente un hilo ejecuta la llamada mientras los demás bloquean y esperan ese resultado.

**A favor**
- **Portable**: la única que funciona igual en AWS, GCP y el adaptador local, y por tanto la única viable como base del adaptador de GCP.
- Es el enfoque con el que el caso documentado obtuvo el **77 % de reducción del coste de KMS**.
- El refresco tras escritura sirve contenido ligeramente rancio durante el refresco, evitando el pico de latencia de la expiración estricta.
- Control total sobre el TTL, que aquí es un control de seguridad.

**En contra**
- Es código criptográfico propio: hay que escribirlo, probarlo bajo concurrencia real y mantenerlo. Un error reintroduce el problema que se quería evitar.
- No aporta las salvaguardas del SDK (límite de mensajes y bytes por clave), que hay que implementar aparte.
- No satisface el requisito del DB-ESDK para búsqueda sobre campos cifrados.

## Decisión

**Se adopta el hierarchical keyring (opción C) como ruta por defecto en AWS, y la caché con carga atómica explícita (opción D) donde el keyring no es aplicable: adaptador de GCP, adaptador local y cualquier adaptador propio. Se prohíbe el `CachingCryptoMaterialsManager` en funciones con concurrencia alta y en contenedores multihilo**, que es la totalidad del despliegue productivo.

El argumento decisivo tiene dos partes. El keyring resuelve el *stampede* en las **dos** formas que adopta aquí —intraproceso en contenedores y entre entornos en Lambda—, porque la branch key es compartida y persistente. Y es además la primitiva que exige el DB-ESDK, de modo que una sola decisión cubre dos requisitos que de otro modo competirían. La opción D no es un consuelo para GCP: allí es **obligatoria**.

**Corrección explícita del spec original.** La única redacción admisible es: *«Evitar el CCMM en entornos concurrentes; usar hierarchical keyring (recomendación de AWS) o caché con carga atómica; el caso NICE Actimize reporta 77 % de reducción de coste de KMS con este último enfoque.»*

El TTL se trata como **control de seguridad**, porque implica claves en claro en memoria:

| Tier de sensibilidad | TTL |
|---|---|
| `DEDICADO` (datos biométricos activos) | **60 s** |
| `REGULADO` | **300 s** |
| `STANDARD` | **900 s** |

El TTL de una hora de la implementación de referencia externa es demasiado largo para eKYC.

## Consecuencias

### Positivas

- Se elimina el modo de fallo del CCMM antes de escribir la primera línea.
- Una sola decisión cubre escala y búsqueda sobre campos cifrados en AWS.
- El *stampede* entre entornos fríos de Lambda queda mitigado sin trabajo adicional.
- El TTL por sensibilidad convierte la ventana de exposición ante volcado de memoria en un parámetro explícito.

### Negativas

- Dos implementaciones de la misma preocupación —keyring en AWS, caché propia en GCP— cuyo comportamiento debe converger y verificarse.
- La tabla de branch keys es una dependencia nueva en el camino crítico.
- La caché con carga atómica es código criptográfico propio, con su coste de revisión y de pruebas bajo concurrencia.
- Los TTL cortos del tier `DEDICADO` reducen los aciertos y elevan las llamadas a KMS: intercambio consciente de coste por ventana de exposición.

### Neutras

- La instrumentación es parte de la decisión: `crypto.unique_data_keys_ratio` con alarma por encima de **0,05** (el caso patológico alcanzó **0,30**), `crypto.kms_calls_per_operation`, `crypto.cache_hit_ratio`, `crypto.cache_load_contention` y `crypto.decrypt_failures_by_context`.
- La última cumple doble función: salud criptográfica y detección de errores de alcance de tenant.

## Criterios de revisión

- **Si `crypto.unique_data_keys_ratio` supera 0,05** de forma sostenida, la caché no está coordinando: hay que auditar la implementación antes de ampliar capacidad.
- **Si AWS corrige el CCMM** con carga coordinada, procede reevaluar si el keyring sigue justificando la tabla de branch keys —aunque el requisito del DB-ESDK se mantendría.
- **Si GCP publica una primitiva equivalente** o Tink incorpora caché mantenida, la caché propia debe sustituirse: menos código criptográfico propio es menos riesgo.
- **Si el modelo de ejecución cambia** —de Lambda a contenedores de larga vida—, la forma del *stampede* cambia y hay que revalidar TTL y dimensionado.
- **Si el coste de KMS por sesión supera el presupuesto** pese a los aciertos, la palanca es la jerarquía de claves, no alargar el TTL de los tiers sensibles.

## Referencias

- [Caching KMS data keys in multi-thread environments — AWS Security Blog](https://aws.amazon.com/blogs/security/caching-kms-data-keys-in-multi-thread-environments-per-tenant-encryption-for-event-driven-systems-at-scale/)
- [aws-arquitecturas-de-referencia — Ficha 3 y verificación de cifras, punto 2](../referencias/aws-arquitecturas-de-referencia.md)
- [AWS KMS request quotas](https://docs.aws.amazon.com/kms/latest/developerguide/requests-per-second.html)
- [Lambda quotas — burst de 1.000 entornos cada 10 s por función](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [AWS Database Encryption SDK — Choosing a beacon length](https://docs.aws.amazon.com/database-encryption-sdk/latest/devguide/choosing-beacon-length.html)
- [Tink issue #697 — rendimiento del Envelope AEAD sobre Cloud KMS](https://github.com/google/tink/issues/697)
- [gcp-paridad-de-servicios §3, brecha 4](../referencias/gcp-paridad-de-servicios.md)
