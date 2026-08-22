# 00 — Índice y mapa de lectura

| Campo | Valor |
|---|---|
| **Estado** | Aprobado |
| **Versión** | 1.1.0 |
| **Última actualización** | 2026-08-21 |
| **Responsable** | Arquitectura de la plataforma |
| **Audiencia** | Todos los roles |
| **Documentos relacionados** | Todos los de esta carpeta · [`adr/`](adr/) · [`referencias/`](referencias/) · [`../README.md`](../README.md) |

**Resumen ejecutivo.** Este documento es el punto de entrada único a la documentación de **Onboarding Genérico**, un middleware B2B transaccional y serverless que se interpone entre los sistemas requirentes de onboarding y los proveedores de capacidades de verificación de identidad, y que compone dinámicamente el flujo según tenant, país, tipo de documento y nivel de aseguramiento. Aquí está el inventario completo de documentos, la ruta de lectura recomendada por rol —arquitecto, desarrollador, SRE, oficial de cumplimiento y comercial— y los enlaces a los artefactos que viven fuera de `docs/`: los registros de decisión, la infraestructura como código y el contrato de API. Toda cifra cuantitativa de esta documentación es trazable a [`referencias/`](referencias/); lo que no lo es, está marcado como pendiente de verificar.

---

## 1. Inventario de documentos

### 1.1 Fundamentos

| Documento | Propósito |
|---|---|
| [01 — Visión y alcance](01-vision-y-alcance.md) | Problema, propuesta de valor, actores, casos de uso CU-01..CU-12, requisitos RF-xx y RNF-xx con métricas objetivo, fuera de alcance y glosario bilingüe |
| [02 — Arquitectura](02-arquitectura.md) | Principios, vistas C4 (contexto, contenedores, componentes), arquitectura hexagonal, catálogo de puertos con adaptadores AWS/GCP/local, flujo transaccional de una sesión |
| [03 — Modelo de dominio](03-modelo-de-dominio.md) | Entidades e invariantes, máquinas de estado, esquema de tabla única con patrones de acceso AP-01..AP-20 y su traducción al modelo documental |

### 1.2 El motor

| Documento | Propósito |
|---|---|
| [04 — Motor de composición](04-motor-de-composicion.md) | Registro de capacidades con su estado de madurez, esquema de la especificación de flujo, resolución, validación, compilación a ASL y a YAML, versionado sin desplegar código y `fallback_provider` |
| [07 — Orquestación](07-orquestacion.md) | Orquestación híbrida Standard/Express, cuotas reales, `.waitForTaskToken`, punteros en lugar de payloads, cálculo de coste y mapeo a Cloud Workflows |

### 1.3 Seguridad y datos

| Documento | Propósito |
|---|---|
| [05 — Multitenancy y aislamiento](05-multitenancy-y-aislamiento.md) | Modelos silo/pool/bridge por tier, cadena Cognito → pre-token-generation → `AssumeRoleWithWebIdentity` → `LeadingKeys`, políticas transcritas, brecha de GCP y tabla de controles por nivel de garantía |
| [06 — Criptografía y gestión de claves](06-criptografia-y-gestion-de-claves.md) | Cifrado de sobre por tenant, directivas por atributo, *hierarchical keyring* (y por qué no `CachingCryptoMaterialsManager`), beacons de búsqueda, `tenant_id` como AAD, crypto-shredding y la alternativa de Tink en GCP |
| [12 — Retención y borrado](12-retencion-y-borrado.md) | Colisión entre derecho de supresión y obligación AML, matriz de retención por jurisdicción, flujo de purga con mutex distribuido y regla de quién fija el plazo |
| [14 — Modelo de amenazas](14-modelo-de-amenazas.md) | STRIDE por componente, amenazas específicas de eKYC (inyección de medios, *deepfakes*, *replay*, ataque de tenant a tenant, envenenamiento del registro, *prompt injection*), controles y plan de pruebas |

### 1.4 Capacidades de verificación

| Documento | Propósito |
|---|---|
| [08 — IA y extracción semántica](08-ia-y-extraccion-semantica.md) | Pipeline OCR espacial + LLM, validación MRZ, diseño del prompt, *prompt caching* real, umbrales y derivación, mapeo semántico multipaís y mitigación de inyección |
| [09 — Biometría y liveness](09-biometria-y-liveness.md) | Cotejo 1:1 con umbrales normativos, PAD conforme a ISO/IEC 30107-3, calidad de imagen, ataques de inyección, brecha de GCP y recomendación de proveedor certificado |

### 1.5 Multinube y cumplimiento

| Documento | Propósito |
|---|---|
| [10 — Multinube AWS y GCP](10-multicloud-aws-gcp.md) | Matriz maestra de equivalencias, las nueve brechas de paridad ordenadas por impacto, la regla "GCP dicta la forma del puerto", clasificación de puertos por fricción y guía de elección de nube |
| [11 — Cumplimiento normativo](11-cumplimiento-normativo.md) | Matriz consolidada Bolivia / Paraguay / México / UE, encargado del tratamiento (art. 28 GDPR), NIST SP 800-63-4 IAL2, GAFI R.10, art. 32(II) del Instructivo UIF, reforma CNBV de julio de 2026 y calendario 2026–2027 |

### 1.6 Operación

| Documento | Propósito |
|---|---|
| [13 — Observabilidad y SRE](13-observabilidad-y-sre.md) | Telemetría sin PII, propagación de `correlation_id` y `tenant_id`, SLI/SLO con presupuesto de error, métricas de negocio, alertas y runbooks RB-01..RB-06 |
| [16 — Guía de despliegue en AWS](16-guia-de-despliegue-aws.md) | Procedimiento paso a paso: prerrequisitos, cuentas, bootstrap de Terraform, orden de módulos, alta de tenant, imágenes en ECR, prueba de humo y lista de verificación |
| [17 — Guía de despliegue en GCP](17-guia-de-despliegue-gcp.md) | Equivalente para GCP, señalando en cada paso qué difiere de AWS y qué brechas obligan a trabajo adicional |
| [18 — Desarrollo local](18-desarrollo-local.md) | Entorno local con adaptadores en memoria, ejecución de pruebas, flujo de contribución y cómo añadir un adaptador de proveedor paso a paso |

### 1.7 Gobierno del proyecto

| Documento | Propósito |
|---|---|
| [15 — Catálogo de proveedores y licencias](15-catalogo-de-proveedores-y-licencias.md) | Licencias verificadas con veredicto de aptitud comercial, política de licencias del proyecto, advertencia sobre licencias de **pesos de modelos** y ficha por componente |
| [19 — Roadmap](19-roadmap.md) | Fases con entregables y criterios de salida alineados con hitos regulatorios reales, incorporación incremental de países y matriz de riesgos |
| [20 — Fe de erratas del spec original](20-fe-de-erratas-del-spec-original.md) | Las ocho afirmaciones del documento fuente que fueron verificadas y corregidas, con veredicto, evidencia y redacción correcta |

### 1.8 Material fuera de `docs/`

| Artefacto | Contenido | Quién lo mantiene |
|---|---|---|
| [`adr/`](adr/) | Registros de decisión de arquitectura. Toda decisión irreversible tiene su ADR | Arquitectura |
| [`referencias/`](referencias/) | Investigación verificada de agosto de 2026. **Fuente de verdad de toda cifra citada.** Solo lectura | Arquitectura |
| [`../infra/terraform/README.md`](../infra/terraform/README.md) | Estructura de módulos, entornos y convenciones de la infraestructura como código | Plataforma |
| [`../api/openapi.yaml`](../api/openapi.yaml) | Contrato de la API pública v1: rutas, esquemas, códigos de error e idempotencia | Producto y desarrollo |
| [`../README.md`](../README.md) | Presentación del repositorio, arranque rápido y estructura de carpetas | Todos |

<!-- PENDIENTE DE VERIFICAR: `api/openapi.yaml` y `README.md` raíz los generan otros equipos en esta misma entrega; si el enlace no resuelve, el archivo aún no ha aterrizado. -->

---

## 2. Rutas de lectura por rol

### 2.1 Arquitecto

**Ruta principal, en orden:**

1. [01 — Visión y alcance](01-vision-y-alcance.md) — el problema y sus fronteras; los RNF con métrica son el contrato implícito de todo lo demás
2. [02 — Arquitectura](02-arquitectura.md) — principios, vistas C4 y decisiones de acoplamiento
3. [03 — Modelo de dominio](03-modelo-de-dominio.md) — invariantes y esquema
4. [04 — Motor de composición](04-motor-de-composicion.md) — el núcleo del producto
5. [10 — Multinube](10-multicloud-aws-gcp.md) — dónde y por qué divergen las nubes

**Lea con especial atención**, porque contienen decisiones irreversibles:

| Punto | Documento |
|---|---|
| La longitud de beacon **no puede cambiarse** tras escribir registros | [06 §6.2](06-criptografia-y-gestion-de-claves.md) |
| El esquema de claves **no es retrofit-able**: `LeadingKeys` exige prefijo de tenant desde el día cero | [05 §4](05-multitenancy-y-aislamiento.md), [03 §4.1](03-modelo-de-dominio.md) |
| La brecha de aislamiento de GCP **invierte la dirección del diseño de puertos** | [05 §6.4](05-multitenancy-y-aislamiento.md), [10 §4](10-multicloud-aws-gcp.md) |
| El puerto de repositorio **no expone `PK`/`SK`**; si lo hace, el adaptador documental es inviable | [03 §4.7](03-modelo-de-dominio.md) |

**Después:** [20 — Fe de erratas](20-fe-de-erratas-del-spec-original.md), para entender por qué el repositorio contradice el spec original en ocho puntos, y [`adr/`](adr/) para el registro de decisiones.

### 2.2 Desarrollador

**Empiece por:**

1. [18 — Desarrollo local](18-desarrollo-local.md) — instalación y primer recorrido completo en local
2. [02 §5–6](02-arquitectura.md) — puertos, adaptadores y taxonomía de errores
3. [03](03-modelo-de-dominio.md) — entidades e invariantes
4. [`../api/openapi.yaml`](../api/openapi.yaml) — el contrato que consume el requirente

**Según lo que vaya a tocar:**

| Trabajo | Documentos |
|---|---|
| Adaptador de proveedor nuevo (*el caso más frecuente*) | [18 §7](18-desarrollo-local.md), [02 §6](02-arquitectura.md), [15 §6](15-catalogo-de-proveedores-y-licencias.md) |
| País o documento nuevo | [18 §8](18-desarrollo-local.md), [08 §4.5–4.7](08-ia-y-extraccion-semantica.md), [04 §5](04-motor-de-composicion.md) |
| Extracción documental | [08](08-ia-y-extraccion-semantica.md) completo |
| Biometría | [09](09-biometria-y-liveness.md) completo |
| Criptografía | [06](06-criptografia-y-gestion-de-claves.md) completo — **doble aprobación obligatoria** |
| Orquestación | [07](07-orquestacion.md) completo |
| Motor de composición | [04](04-motor-de-composicion.md) completo |
| Infraestructura | [`../infra/terraform/README.md`](../infra/terraform/README.md), [16](16-guia-de-despliegue-aws.md) §4, [17](17-guia-de-despliegue-gcp.md) §4 |

**Antes de su primer *pull request*:** [18 §9](18-desarrollo-local.md) — convenciones, puertas de calidad y cuándo hace falta un ADR.

### 2.3 SRE

**Ruta principal:**

1. [13 — Observabilidad y SRE](13-observabilidad-y-sre.md) — telemetría, SLI/SLO y los runbooks RB-01..RB-06
2. [16 — Despliegue AWS](16-guia-de-despliegue-aws.md) o [17 — Despliegue GCP](17-guia-de-despliegue-gcp.md), según la nube
3. [07 §10](07-orquestacion.md) — fallos de orquestación y su tratamiento
4. [12 §6](12-retencion-y-borrado.md) — el proceso de purga y su mutex

**Antes de la primera guardia**, tenga a mano:

- Los runbooks RB-01 a RB-06 ([13 §5.2](13-observabilidad-y-sre.md))
- La tabla de solución de problemas de su nube ([16 §10](16-guia-de-despliegue-aws.md) / [17 §13](17-guia-de-despliegue-gcp.md))
- El inventario de cuotas vigiladas ([13 §6](13-observabilidad-y-sre.md))

**Dos señales que no son incidentes de disponibilidad sino de seguridad:**

- `crypto.decrypt_failures_by_context > 0` → runbook RB-04, y **descarte primero la hipótesis de fuga entre tenants**
- SLI-7 (corrección del aislamiento) en fallo → severidad 1 inmediata, con notificación al responsable de cumplimiento

### 2.4 Oficial de cumplimiento

**Ruta principal:**

1. [11 — Cumplimiento normativo](11-cumplimiento-normativo.md) — el marco completo por jurisdicción; empiece por §1.1, "Lo que este documento NO es"
2. [12 — Retención y borrado](12-retencion-y-borrado.md) — cómo se resuelve la colisión entre retención AML y derecho de supresión
3. [09 §4](09-biometria-y-liveness.md) — las métricas PAD correctas y lo que las certificaciones **no** acreditan
4. [11 §7](11-cumplimiento-normativo.md) — los controles técnicos trazables a requisitos normativos

**Los cuatro puntos que exigen su intervención:**

| Punto | Documento |
|---|---|
| **El inventario de lo no verificado**: 15 elementos que requieren fuente primaria antes de comprometerse contractualmente | [11 §8](11-cumplimiento-normativo.md) |
| **La restricción boliviana** sobre delegación de la debida diligencia: determina la viabilidad del modelo de negocio | [11 §3.3](11-cumplimiento-normativo.md) |
| **La política de retención la fija el responsable**, no el middleware | [12 §7](12-retencion-y-borrado.md) |
| **El paquete de asistencia para la DPIA**: requisito de facto para vender en Europa | [11 §4.3](11-cumplimiento-normativo.md) |

**Para preparar una auditoría:** [11 §7](11-cumplimiento-normativo.md) (mapeo de controles) más [14 §8](14-modelo-de-amenazas.md) (pruebas de penetración) más [12 §9](12-retencion-y-borrado.md) (verificación de purga).

### 2.5 Comercial

**Ruta corta:**

1. [01 §2](01-vision-y-alcance.md) — la propuesta de valor, y §5.2, **qué NO promete el producto**
2. [19 §1](19-roadmap.md) — las fechas regulatorias que abren ventana comercial
3. [11 §2](11-cumplimiento-normativo.md) — la matriz consolidada por jurisdicción
4. [10 §6.4](10-multicloud-aws-gcp.md) — cómo se responde a un cliente que exige su nube

**Cinco afirmaciones que NO debe hacer, y su razón:**

| No diga | Porque | Documento |
|---|---|---|
| *"Resolvemos el fraude de identidad sintética"* | El producto **contribuye pero no lo resuelve**: si el documento es auténtico y la persona está viva, no hay señal técnica que emitir | [14 §4.2](14-modelo-de-amenazas.md) |
| *"En GCP el aislamiento es igual que en AWS"* | GCP **no tiene barrera en el plano de datos**. La formulación correcta está en [05 §6.5](05-multitenancy-y-aislamiento.md) | [05 §6](05-multitenancy-y-aislamiento.md) |
| *"Certificación de nivel 2 significa baja fricción"* | El BPCER admitido por la certificación es del **15 %**; un producto comercial necesita 2–5 % | [09 §4.3](09-biometria-y-liveness.md) |
| *"Nuestro ACER es del X %"* | **ACER no es métrica normativa** de ISO/IEC 30107-3. Se reportan APCER por especie y BPCER | [09 §4.2](09-biometria-y-liveness.md) |
| *"Realizamos su KYC"* — en Bolivia | El art. 32(II) del Instructivo UIF prohíbe delegar la ejecución de la debida diligencia | [11 §3.3](11-cumplimiento-normativo.md) |

**Argumento fuerte disponible:** la cadena GAFI → NIST → ISO de [11 §5.4](11-cumplimiento-normativo.md) es la respuesta a un oficial de cumplimiento conservador que sostenga que lo remoto es intrínsecamente de mayor riesgo.

---

## 3. Convenciones de esta documentación

| Convención | Significado |
|---|---|
| Tabla de metadatos al inicio | Estado, versión, última actualización, responsable, audiencia y documentos relacionados |
| Resumen ejecutivo de 3–5 líneas | Inmediatamente después de la tabla de metadatos |
| Sección "Referencias" al final | Enlaces a la investigación de origen y a los documentos hermanos |
| `<!-- PENDIENTE DE VERIFICAR -->` | Afirmación **no** respaldada por la investigación, que requiere fuente primaria. Aparece en el código fuente del documento; el inventario consolidado está en [11 §8](11-cumplimiento-normativo.md) y [19 §4](19-roadmap.md) |
| 🔴 | Brecha crítica o decisión irreversible |
| ⚠️ | Advertencia que suele pasarse por alto |
| `> **Decisión requerida:**` | En las guías de despliegue: punto donde el operador elige, con consecuencias difíciles de revertir |
| Identificadores estables | `CU-xx` casos de uso · `RF-xx` requisitos funcionales · `RNF-xx` no funcionales · `AP-xx` patrones de acceso · `RB-xx` runbooks · `SLI-x` indicadores · `E-xx` erratas · `T-xx` amenazas |
| Diagramas | Siempre en Mermaid, nunca ASCII |
| Idioma | Español latinoamericano sin voseo en prosa; inglés en identificadores de código, nombres de archivo, ramas y mensajes de *commit* |

---

## 4. Los cinco hechos que conviene conocer antes de tocar nada

1. **La longitud de beacon se mide en bits y no puede cambiarse tras escribir registros.** Es la decisión más irreversible del sistema ([06 §6.2](06-criptografia-y-gestion-de-claves.md)).
2. **`dynamodb:LeadingKeys` no es retrofit-able**, y **no protege los índices globales** salvo que su clave de partición lleve el tenant ([05 §4](05-multitenancy-y-aislamiento.md)).
3. **GCP no tiene equivalente al aislamiento en el plano de datos**, y la brecha es silenciosa: el código funciona, simplemente no está aislado ([05 §6](05-multitenancy-y-aislamiento.md)).
4. **El `CachingCryptoMaterialsManager` es la causa del problema de estampida, no la solución**; la recomendación correcta es el *hierarchical keyring* ([06 §5](06-criptografia-y-gestion-de-claves.md), [20 E-03](20-fe-de-erratas-del-spec-original.md)).
5. **La política de retención la fija el responsable del tratamiento, no el middleware.** Elegirla unilateralmente reclasifica al operador como corresponsable ([12 §7](12-retencion-y-borrado.md)).

---

## Referencias

- [`referencias/aws-arquitecturas-de-referencia.md`](referencias/aws-arquitecturas-de-referencia.md) — patrones de multi-tenancy, cifrado, orquestación y flujos dinámicos en AWS, con verificación de cifras y cuotas oficiales.
- [`referencias/gcp-paridad-de-servicios.md`](referencias/gcp-paridad-de-servicios.md) — matriz de equivalencias AWS→GCP, límites reales y brechas críticas de paridad.
- [`referencias/cumplimiento-normativo-y-estandares.md`](referencias/cumplimiento-normativo-y-estandares.md) — ICAO Doc 9303, ISO/IEC 30107-3, NIST SP 800-63-4, eIDAS 2.0, GDPR, México, Bolivia, Paraguay, GAFI y retención.
- [`adr/`](adr/) — registros de decisión de arquitectura.
- [`../infra/terraform/README.md`](../infra/terraform/README.md) · [`../api/openapi.yaml`](../api/openapi.yaml) · [`../README.md`](../README.md)
