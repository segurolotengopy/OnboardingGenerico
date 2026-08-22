I have enough material. Here is the research deliverable.

---

# Marco normativo aplicable a un middleware B2B de onboarding / eKYC con biometría facial y lectura documental
### Alcance: Bolivia · Paraguay · México · Unión Europea | Estado de verificación: agosto 2026

> **Convenciones de esta investigación**
> - ✅ **Verificado en fuente primaria u oficial** (texto normativo, organismo emisor).
> - 🟡 **Verificado sólo en fuente secundaria** (bufete, prensa especializada, proveedor). Requiere contraste contra el texto oficial antes de usarse en un compromiso contractual.
> - ❌ **NO verificado en esta sesión** — se indica explícitamente y no se sustituye por estimaciones.
> - 🔄 **Cambio reciente** (2025–2026) que altera el diseño del producto.

---

# A. ESTÁNDARES TÉCNICOS

## A.1 — ICAO Doc 9303: MRZ, formatos TD1/TD2/TD3 y dígitos de control

### A.1.1 Algoritmo del dígito de control ✅

ICAO Doc 9303 Parte 3, sección 4.9, establece textualmente:

> *"Check digits shall be calculated on modulus 10 with a continuously repetitive weighting of 731 731 …"*

Procedimiento normativo en cuatro pasos (cita literal del estándar):

1. **Step 1.** *"Going from left to right, multiply each digit of the pertinent numerical data element by the weighting figure appearing in the corresponding sequential position."*
2. **Step 2.** *"Add the products of each multiplication."*
3. **Step 3.** *"Divide the sum by 10 (the modulus)."*
4. **Step 4.** *"The remainder shall be the check digit."*

**Tabla de valores de carácter** ✅

| Carácter | Valor |
|---|---|
| `0`–`9` | Valor nominal (0–9) |
| `A`–`Z` | 10–35 consecutivos (`A`=10, `B`=11 … `Z`=35) |
| `<` (filler) | 0 |

**Pseudocódigo exacto**

```
FUNCION check_digit(cadena):
    pesos = [7, 3, 1]
    suma  = 0
    PARA i, c EN enumerar(cadena):          # i base 0
        SI c ES dígito:        v = int(c)
        SI NO SI c ES 'A'..'Z': v = ord(c) - ord('A') + 10
        SI NO SI c == '<':      v = 0
        SI NO:                  ERROR carácter inválido en MRZ
        suma += v * pesos[i mod 3]
    DEVOLVER suma mod 10
```

**Ejemplo trabajado** (número de documento `D23145890`):

| Pos | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Carácter | D | 2 | 3 | 1 | 4 | 5 | 8 | 9 | 0 |
| Valor | 13 | 2 | 3 | 1 | 4 | 5 | 8 | 9 | 0 |
| Peso | 7 | 3 | 1 | 7 | 3 | 1 | 7 | 3 | 1 |
| Producto | 91 | 6 | 3 | 7 | 12 | 5 | 56 | 27 | 0 |

Suma = 207 → 207 mod 10 = **7** → coincide con el dígito de control `7` que aparece en el ejemplo canónico ICAO (`D231458907`). ✅

### A.1.2 Dígito de control compuesto (*composite check digit*) ✅ / 🟡

El compuesto se calcula **sobre la concatenación de subcadenas ya incluyendo sus propios dígitos de control**, aplicando el mismo esquema 7-3-1 **reiniciado desde el peso 7 al inicio de la concatenación** (no se continúa la secuencia de pesos de cada campo por separado).

| Formato | Rangos cubiertos por el compuesto | Posición del compuesto | Verificación |
|---|---|---|---|
| **TD1** | Línea 1 pos. 6–30 + Línea 2 pos. 1–7, 9–15, 19–29 | Línea 2, pos. 30 | 🟡 (no pude descargar Doc 9303 Parte 5; el rango se corresponde con la definición ICAO y es consistente con la lógica TD2/TD3) |
| **TD2** | Línea 2 pos. 1–10 + 14–20 + 22–35 | Línea 2, pos. 36 | ✅ |
| **TD3** | Línea 2 pos. 1–10 + 14–20 + 22–43 | Línea 2, pos. 44 | ✅ |

Obsérvese que en TD1 el compuesto **sí incluye el campo de datos opcionales de la línea superior** (pos. 16–30) — este es el error de implementación más común. Una fuente secundaria consultada omitía ese tramo; **la definición ICAO lo incluye**. ⚠️ Recomiendo validar contra Doc 9303 Parte 5 antes de fijar la implementación.

### A.1.3 Estructura de campos por formato

**TD1 — 3 líneas × 30 caracteres (90 total)** — tarjetas de identidad, permisos de residencia ✅

| Línea | Posiciones | Campo | Long. |
|---|---|---|---|
| 1 | 1–2 | Código de documento (`I`, `A`, `C` + subtipo) | 2 |
| 1 | 3–5 | Estado emisor (código ICAO 3 letras) | 3 |
| 1 | 6–14 | Número de documento | 9 |
| 1 | 15 | **CD** número de documento | 1 |
| 1 | 16–30 | Datos opcionales 1 | 15 |
| 2 | 1–6 | Fecha de nacimiento (YYMMDD) | 6 |
| 2 | 7 | **CD** fecha de nacimiento | 1 |
| 2 | 8 | Sexo (`M`/`F`/`<`) | 1 |
| 2 | 9–14 | Fecha de expiración (YYMMDD) | 6 |
| 2 | 15 | **CD** fecha de expiración | 1 |
| 2 | 16–18 | Nacionalidad | 3 |
| 2 | 19–29 | Datos opcionales 2 | 11 |
| 2 | 30 | **CD compuesto** | 1 |
| 3 | 1–30 | Nombre (apellido `<<` nombres, relleno `<`) | 30 |

Ejemplo canónico ICAO:
```
I<UTOD231458907<<<<<<<<<<<<<<<
7408122F1204159UTO<<<<<<<<<<<6
ERIKSSON<<ANNA<MARIA<<<<<<<<<<
```

**TD2 — 2 líneas × 36 caracteres (72 total)** ✅

| Línea | Posiciones | Campo | Long. |
|---|---|---|---|
| 1 | 1–2 | Código de documento | 2 |
| 1 | 3–5 | Estado emisor | 3 |
| 1 | 6–36 | Nombre | 31 |
| 2 | 1–9 | Número de documento | 9 |
| 2 | 10 | **CD** número de documento | 1 |
| 2 | 11–13 | Nacionalidad | 3 |
| 2 | 14–19 | Fecha de nacimiento | 6 |
| 2 | 20 | **CD** fecha de nacimiento | 1 |
| 2 | 21 | Sexo | 1 |
| 2 | 22–27 | Fecha de expiración | 6 |
| 2 | 28 | **CD** fecha de expiración | 1 |
| 2 | 29–35 | Datos opcionales | 7 |
| 2 | 36 | **CD compuesto** | 1 |

```
I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<
D231458907UTO7408122F1204159<<<<<<<6
```

**TD3 — 2 líneas × 44 caracteres (88 total)** — pasaportes ✅

| Línea | Posiciones | Campo | Long. |
|---|---|---|---|
| 1 | 1–2 | Código de documento (`P<`) | 2 |
| 1 | 3–5 | Estado emisor | 3 |
| 1 | 6–44 | Nombre | 39 |
| 2 | 1–9 | Número de pasaporte | 9 |
| 2 | 10 | **CD** número de pasaporte | 1 |
| 2 | 11–13 | Nacionalidad | 3 |
| 2 | 14–19 | Fecha de nacimiento | 6 |
| 2 | 20 | **CD** fecha de nacimiento | 1 |
| 2 | 21 | Sexo | 1 |
| 2 | 22–27 | Fecha de expiración | 6 |
| 2 | 28 | **CD** fecha de expiración | 1 |
| 2 | 29–42 | Número personal / datos opcionales | 14 |
| 2 | 43 | **CD** número personal | 1 |
| 2 | 44 | **CD compuesto** | 1 |

```
P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<
L898902C36UTO7408122F1204159ZE184226B<<<<<10
```

> **Nota de implementación (TD3):** cuando el campo de número personal está vacío (`<<<<<<<<<<<<<<`), Doc 9303 permite que el CD de la posición 43 sea `<` en lugar de `0`. Un parser robusto debe aceptar ambos. 🟡

**Fuentes A.1**
- [ICAO Doc 9303 Parte 3 (consolidado)](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf) — algoritmo 7-3-1, sección 4.9 (los layouts por factor de forma están en Partes 4–7)
- [idcheck.dev — ICAO 9303 check digits](https://idcheck.dev/icao-9303-check-digits/) — rangos del compuesto TD2/TD3
- [mrz.codes](https://mrz.codes/) — layout TD3 y ejemplo
- [doubango KYC docs — MRZ](https://www.doubango.org/SDKs/kyc-documents-verif/docs/MRZ.html) — layouts TD1/TD2/TD3 y ejemplos canónicos
- [mrzcalculator.com — guía TD1](https://mrzcalculator.com/td1-id-card-mrz-guide)

---

## A.2 — ISO/IEC 30107-3: Presentation Attack Detection

### A.2.1 Métricas normativas ✅ / 🔄

| Métrica | Definición | Estatus normativo |
|---|---|---|
| **APCER** — *Attack Presentation Classification Error Rate* | Proporción de presentaciones de ataque (por especie PAI) clasificadas incorrectamente como bona fide. Mide **seguridad**. Se reporta **por especie**, y el resultado global es el **peor caso** entre especies. | Normativa en 30107-3:2017 y :2023 |
| **BPCER** — *Bona Fide Presentation Classification Error Rate* | Proporción de presentaciones legítimas clasificadas incorrectamente como ataque. Mide **usabilidad / fricción**. | Normativa en ambas ediciones |
| **IAPAR** — *Impostor Attack Presentation Accept Rate* (antes IAPMR) | Probabilidad de que un ataque contra el **sistema biométrico completo** (PAD + matcher) sea aceptado. Es la métrica de *end-to-end*, no de subsistema. | Normativa |
| **RIAPAR** — *Relative IAPAR* | 🔄 **Introducida como métrica obligatoria en la edición 2023.** Combina seguridad y conveniencia (IAPAR + FRR), para evitar que un proveedor optimice una métrica a costa de la otra. | Obligatoria desde :2023 |
| **ACER** — *Average Classification Error Rate* = (APCER+BPCER)/2 | ⚠️ **Advertencia importante:** ACER es de uso extendido en literatura académica y marketing de proveedores, pero **no es la métrica normativa de reporte de ISO/IEC 30107-3**. La norma exige reportar APCER y BPCER **por separado** (y RIAPAR desde 2023), precisamente porque promediarlas oculta el peor caso de ataque. **No se debe aceptar un ACER como evidencia de conformidad 30107-3.** | 🟡 (uso extendido documentado; que ACER haya sido formalmente eliminado del texto de la edición 2023 **no pude confirmarlo** ❌) |

### A.2.2 Niveles iBeta (Levels 1 / 2 / 3) 🟡

iBeta Quality Assurance (Denver, EE. UU.) es el laboratorio de referencia de facto, acreditado NVLAP para pruebas de conformidad con ISO/IEC 30107-3. Sus "niveles" **no son niveles de la norma ISO** — son un protocolo comercial de iBeta que define el presupuesto y sofisticación de los artefactos de ataque.

| Parámetro | **Nivel 1** | **Nivel 2** |
|---|---|---|
| Tiempo por sujeto/especie | 8 horas | 2–4 días |
| Pericia del atacante | *"None"* — sujeto cooperativo, equipo de hogar/oficina normal | *"Moderate"* — personal con ≥1 prueba PAD previa en la modalidad |
| Coste máximo del artefacto | **US$ 30** | **US$ 300** |
| Artefactos típicos | Foto impresa, foto en pantalla, vídeo replay, máscara de papel | Impresión 3D, máscara de resina, máscara de látex |
| Especies PAI (PAIS) | **6** | **6** |
| Presentaciones (protocolo *liveness-only*) | ~**150 ataques** alternados con **50 presentaciones genuinas** | (protocolo análogo, mayor duración) |
| **Criterio de aprobación — tasa de penetración/match** | **0 %** permitido | **1 %** permitido |
| **Criterio de aprobación — BPCER/FNMR** | ≤ **15 %** | ≤ **15 %** |

> ⚠️ El BPCER admitido por iBeta (15 %) es **muy laxo** respecto de lo que un onboarding comercial tolera. En producción financiera el objetivo operativo suele ser BPCER ≤ 2–5 % con APCER ≈ 0 en las especies de Nivel 1–2. Ese ajuste **no lo impone la certificación**: es decisión de diseño del middleware. Presentar "iBeta Level 2" como sinónimo de baja fricción es incorrecto.

### A.2.3 Umbrales exigidos por reguladores

| Regulador / marco | Exigencia | Estatus |
|---|---|---|
| **NIST SP 800-63A-4 (EE. UU.)** | PAD obligatorio en recolección biométrica remota, con **IAPAR < 0,07** medido conforme a **ISO/IEC 30107-3:2023** | ✅ |
| **CNBV (México)** | Prueba de vida "certificada" y mecanismos capaces de detectar *deepfakes*, máscaras, fotos estáticas y **ataques de inyección** | 🟡 (redacción vía fuente secundaria; requiere contraste con Anexo 71 del DOF) |
| **eIDAS 2.0 / EUDI** | Sin umbral numérico único; se remite a los actos de ejecución y esquemas de certificación | ❌ no verificado un umbral numérico |
| **ASFI (Bolivia) / BCP-SEPRELAD (Paraguay)** | **No se localizó ninguna exigencia de umbral PAD ni referencia a ISO 30107-3** | ❌ (ver secciones B.8 y B.9) |

> **Vector no cubierto por 30107-3:** los **ataques de inyección** (cámara virtual, hooking del stream, deepfake inyectado en el pipeline) **no son ataques de presentación** y quedan fuera del alcance de 30107-3. La CNBV mexicana ya los menciona expresamente. Un middleware serio necesita controles adicionales (attestation de dispositivo/app, integridad del canal de captura, detección de cámara virtual). Existe trabajo en ISO/IEC 30107-4 y en esquemas tipo IAD, pero **su estado normativo no lo verifiqué** ❌.

**Fuentes A.2**
- [iBeta — ISO 30107-3 PAD Test Methodology and Confirmation Letters](https://www.ibeta.com/iso-30107-3-presentation-attack-detection-confirmation-letters/)
- [axonlab.ai — iBeta Certification Requirements (Level 1, 2, 3)](https://axonlab.ai/ibeta-certification-requirements-overview/)
- [NIST — Busch & Thieme, ISO/IEC 30107-3 standard for testing of PAD](https://www.nist.gov/system/files/documents/2020/09/15/12_buschthieme-ibpc-pad-160504.pdf)
- [ID R&D — What's new in the recent update of ISO/IEC 30107](https://idrnd.medium.com/whats-new-in-the-recent-update-of-iso-iec-30107-for-biometric-a048733c0065) (RIAPAR obligatoria en :2023)
- [ISO/IEC 30107-3:2023 (IEC Webstore)](https://webstore.iec.ch/en/publication/81714)

---

## A.3 — NIST SP 800-63-3 / 800-63-4

### A.3.1 Estado de la revisión 4 — 🔄 CAMBIO RECIENTE ✅

**SP 800-63-4 está PUBLICADA COMO VERSIÓN FINAL.** No es borrador.

| Documento | Fecha de publicación final | Estado |
|---|---|---|
| **SP 800-63A-4** — *Identity Proofing and Enrollment* | **1 de agosto de 2025** ✅ | Final; supersede SP 800-63A |
| **SP 800-63-4** (volumen base) + 63B-4 + 63C-4 | Agosto de 2025 🟡 (NIST publicó "Digital Identity Guidelines Rev 4 – Overview of the Final Version August 2025") | Final; supersede SP 800-63-3 |

Recorrido: borrador inicial (ipd) diciembre 2022 → segundo borrador público (2pd) agosto 2024 → **final agosto 2025**.

**Implicación para el producto:** cualquier documentación comercial que aún cite SP 800-63-3 como vigente está desactualizada. La rev-4 introduce requisitos cuantitativos que la rev-3 no tenía (umbrales FMR/FNMR y PAD explícitos), lo que la hace *citable como especificación técnica* en un contrato B2B — algo que la rev-3 no permitía.

### A.3.2 Niveles de aseguramiento ✅

Las tres dimensiones son **independientes y componibles** (un servicio puede exigir IAL2 + AAL2 + FAL2):

| Dimensión | Niveles | Qué mide |
|---|---|---|
| **IAL** — Identity Assurance Level | IAL1, IAL2, IAL3 | Rigor de la **verificación de identidad y enrolamiento** |
| **AAL** — Authentication Assurance Level | AAL1, AAL2, AAL3 | Robustez de la **autenticación** posterior |
| **FAL** — Federation Assurance Level | FAL1, FAL2, FAL3 | Robustez de las **aserciones federadas** |

**Relevancia para un middleware de onboarding:** el producto opera en el dominio **IAL** (SP 800-63A). AAL/FAL son responsabilidad del cliente B2B salvo que el middleware emita credenciales.

### A.3.3 Fuerza de la evidencia: FAIR / STRONG / SUPERIOR ✅

| Fuerza | Criterios (SP 800-63A-4) |
|---|---|
| **FAIR** | El emisor confirmó la identidad mediante procedimientos formales; la evidencia se entregó a la persona; contiene nombre y una referencia identificativa; posee elementos de seguridad físicos o digitales; los atributos núcleo son validables contra fuentes autoritativas |
| **STRONG** | El emisor siguió procedimientos escritos **sujetos a supervisión regulatoria**; **incluye imagen facial u otro biométrico**; validable criptográficamente; atributos validables contra fuentes autoritativas |
| **SUPERIOR** | Emisor con procedimientos escritos rigurosos; **atributos protegidos criptográficamente con firma digital verificada**; **enrolamiento presencial (attended)**; elementos de seguridad físicos y digitales; **imagen facial u otro biométrico obligatorio** |

**Combinaciones de evidencia — SP 800-63-3 (referencia histórica)** ✅

| Nivel | Combinaciones aceptadas |
|---|---|
| **IAL2** | (a) **Una** pieza SUPERIOR o STRONG *si* la fuente emisora, en su propio proceso de proofing, confirmó la identidad recogiendo ≥2 piezas SUPERIOR/STRONG **y** el CSP valida la evidencia directamente con la fuente emisora; **O** (b) **dos** piezas STRONG; **O** (c) **una** STRONG + **dos** FAIR |
| **IAL3** | (a) Dos SUPERIOR; **O** (b) una SUPERIOR + una STRONG (con la condición de fuente emisora reforzada); **O** (c) dos STRONG + una FAIR |

> ❌ **NO VERIFICADO:** la tabla equivalente **de la rev-4** (SP 800-63A-4). Los intentos de descarga del PDF final fallaron y la versión HTML no expuso la sección normativa de IAL2. La rev-4 reorganiza el modelo (introduce *core attributes*, *confirmation codes* y *continuation codes*) y **es probable que las combinaciones difieran**. **No las estoy transcribiendo desde la rev-3 como si fueran rev-4.** Verificar en `NIST.SP.800-63A-4.pdf` §IAL2 antes de comprometer nada contractualmente.

### A.3.4 IAL2 con verificación remota desatendida — requisitos concretos ✅

Aplicable directamente a un middleware de eKYC:

**Modalidad.** *Remote unattended identity proofing* = resolución, validación y verificación **totalmente automatizadas**, sin agente humano, con la ubicación y el dispositivo bajo control del solicitante.

**Métodos de verificación (vinculación evidencia↔persona).** El CSP **SHALL** verificar el vínculo mediante uno o más de: código de confirmación, protocolos de autenticación/federación, verificación de transacción, **comparación facial visual**, **comparación biométrica automatizada**.

> 🚫 **Prohibición expresa y nueva:** *"Knowledge-based verification (KBV) or knowledge-based authentication SHALL NOT be used for identity verification."* — Las preguntas de conocimiento (KBA) quedan **eliminadas** como método válido. Es uno de los cambios de mayor impacto operativo de la rev-4.

**Umbrales biométricos obligatorios:**

| Requisito | Umbral | Modalidad |
|---|---|---|
| Verificación **1:1** — FMR (tasa de falsa coincidencia) | **≤ 1:10.000** (1×10⁻⁴) o mejor | Obligatorio |
| Verificación **1:1** — FNMR (tasa de falsa no coincidencia) | **≤ 1:100** (1 %) o mejor | Obligatorio |
| Identificación **1:N** — tasa de falso positivo | **≤ 1:1.000** o mejor | Obligatorio |
| Identificación **1:N** — revisión manual | **Obligatoria antes de denegar** el enrolamiento | Obligatorio |
| **Paridad demográfica** | El rendimiento en cualquier grupo demográfico **no puede ser >25 % peor** que el de la población general | Obligatorio |
| **PAD** (recolección biométrica remota) | **IAPAR < 0,07** conforme a **ISO/IEC 30107-3:2023** | Obligatorio |

**Protección antiautomatización.** El CSP debe implementar: *bot detection, mitigation and management*; analítica de comportamiento; configuración de WAF; y análisis de tráfico de red.

### A.3.5 Registro de auditoría y retención — parcialmente verificado 🟡 / ❌

Lo confirmado: el CSP **debe establecer y documentar políticas de "retention, protection, and deletion of all personal, sensitive, and biometric data"**, definir calendarios de retención y procesos de borrado, y consignarlos en su *practice statement*. La sección 3.1 (documentación) recoge la obligación de política de retención.

> ❌ **NO VERIFICADO:** el **período mínimo concreto** de retención de registros de enrolamiento tras el cierre de la cuenta en la rev-4, ni el detalle técnico normativo de los *audit logs*. En SP 800-63-3 existía un requisito de retención de registros vinculado a los calendarios de la NARA (7 años y 6 meses tras la terminación en el caso general), **pero no pude confirmar que se mantenga en la rev-4** y por tanto no lo afirmo.

**Fuentes A.3**
- [NIST SP 800-63-4 (HTML, volumen base)](https://pages.nist.gov/800-63-4/sp800-63.html)
- [NIST SP 800-63A-4 (HTML)](https://pages.nist.gov/800-63-4/sp800-63a.html)
- [NIST — página de publicación SP 800-63A-4 (fecha: 1 ago 2025)](https://www.nist.gov/publications/nist-sp-800-63a-4digital-identity-guidelines-identity-proofing-and-enrollment)
- [NIST — Digital Identity Guidelines Rev 4, Overview of the Final Version (agosto 2025)](https://www.nist.gov/document/digital-identity-guidelines-rev-4-slides)
- [NIST SP 800-63A-4 (PDF final)](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63A-4.pdf) — no descargable en esta sesión
- [NIST SP 800-63-3 (referencia histórica)](https://pages.nist.gov/800-63-3/sp800-63-3.html)

---

## A.4 — Calidad de imagen facial y rendimiento del matching

### A.4.1 ISO/IEC 19794-5 → ISO/IEC 39794-5 🔄

| Norma | Objeto | Estado |
|---|---|---|
| **ISO/IEC 19794-5:2011** | Formato de intercambio de datos de imagen facial (formato "clásico", estructura fija) | Vigente pero **en transición de salida** |
| **ISO/IEC 39794-5:2019** | Formato **extensible** de intercambio de imagen facial — sucesor de 19794-5 para eMRTD | Vigente; adopción en curso |
| **ISO/IEC 29794-5:2025** | 🔄 **Calidad de muestra facial** (distinto de formato). Define componentes de calidad y puntuación unificada; base de la herramienta open source **OFIQ** | Publicada en 2025 |

**Perfil de aplicación ICAO para 39794-5 en eMRTD** ✅ — el *Technical Report* de ICAO especifica:
- Captura y codificación **conforme a ISO/IEC 39794-5 Anexo D.1**
- Valores de género limitados a `Other` / `Male` / `Female`
- Formatos de imagen permitidos: **JPEG, JPEG2000 lossy, JPEG2000 lossless** únicamente
- Sólo bloque de **representación 2D**; representación **3D prohibida** (`MUST NOT be used`)
- `Face image kind` = `MRTD`

> ❌ **NO VERIFICADO — dato crítico para roadmap:** las **fechas exactas de transición** 19794-5 → 39794-5. El TR de perfil de aplicación de ICAO consultado **no contiene calendario**; remite a la nueva edición de Doc 9303 Parte 10. Existen fechas ampliamente citadas en la industria (emisión opcional desde ~2025, obligatoria hacia ~2030) pero **no las he podido confirmar en fuente ICAO y por tanto no las doy por buenas**. Consultar Doc 9303 Parte 10 (edición vigente) directamente.

**Implicación de diseño:** el lector de chip del middleware debe **soportar ambos formatos de DG2 en paralelo** durante toda la ventana de transición. Asumir sólo 19794-5 genera fallos con pasaportes de nueva emisión; asumir sólo 39794-5 rompe con el parque circulante (los pasaportes tienen validez de hasta 10 años).

### A.4.2 NIST FRTE/FRVT — métricas y umbrales de operación 1:1 ✅ / ❌

El programa se denomina hoy **FRTE** (*Face Recognition Technology Evaluation*), antes FRVT. La pista 1:1 evalúa *"accuracy, speed, storage and memory consumption, and resilience"* en aplicaciones civiles, policiales y de seguridad fronteriza.

**Umbrales FMR reportados por NIST en la pista 1:1** ✅

| FMR | Uso en el reporte NIST |
|---|---|
| **10⁻⁶** | Umbral principal de ranking en el conjunto **VISABORDER** |
| **3×10⁻⁴** | Análisis de FMR demográfico |
| **10⁻⁵** | Análisis de FNMR demográfico |
| **10⁻⁴** | Comparación de gemelos (*twins*) |

**Fecha del reporte más reciente:** nuevo informe FRTE 1:1 publicado el **8 de mayo de 2026**; estadísticas de participación actualizadas al **31 de julio de 2026**. ✅

> ❌ **NO VERIFICADO:** valores numéricos concretos de FNMR de los algoritmos líderes por dataset. Las tablas de resultados no fueron extraíbles del HTML de la página. **No invento cifras.** Consultar el PDF del informe FRTE 1:1 más reciente en `pages.nist.gov/frvt/`.

**Umbral operativo recomendable para 1:1 en onboarding financiero:**

La referencia normativa **citable** no es FRTE sino **SP 800-63A-4**: FMR ≤ 10⁻⁴ y FNMR ≤ 10⁻² con paridad demográfica ≤25 % de degradación. FRTE es la **evidencia** de que un algoritmo concreto alcanza esos puntos de operación, no la norma que los exige. La arquitectura correcta es: *el contrato B2B fija el umbral 800-63A-4; el informe FRTE del proveedor de matcher demuestra su cumplimiento.*

**Fuentes A.4**
- [NIST FRTE 1:1 Verification](https://pages.nist.gov/frvt/html/frvt11.html)
- [ICAO — TR: ISO/IEC 39794-5 Application Profile for eMRTDs](https://www.icao.int/sites/default/files/TRIP/Publications/ICAO-TR-39794-5-eMRTD-Application-Profile.pdf)
- [ISO/IEC 39794-5:2019](https://www.iso.org/standard/72156.html) · [ISO/IEC 19794-5:2011](https://www.iso.org/standard/50867.html) · [ISO/IEC 29794-5:2025](https://www.iso.org/standard/81005.html)
- [Biometric Update — Face biometric image quality tool evolves with next ISO standard](https://www.biometricupdate.com/202607/face-biometric-image-quality-tool-evolves-with-next-iso-standard)

---

## A.5 — eIDAS 2.0 / EUDI Wallet

### A.5.1 Marco legal ✅

**Reglamento (UE) 2024/1183** (European Digital Identity Framework Regulation), que modifica el Reglamento eIDAS 910/2014. **Entrada en vigor: 20 de mayo de 2024.** Los **actos de ejecución técnicos** se publicaron el **4 de diciembre de 2024** — esa fecha es el "reloj maestro" del que cuelgan todos los plazos.

### A.5.2 Calendario de obligatoriedad 🟡 (fuente: bufete Baker McKenzie, marzo 2026)

| Hito | Fecha | Sujeto |
|---|---|---|
| Entrada en vigor del Reglamento | 20 may 2024 | — |
| Publicación de actos de ejecución técnicos | 4 dic 2024 | — |
| **Estados miembros deben ofrecer ≥1 EUDI Wallet** | **6 dic 2026** (24 meses tras los actos) | Estados miembros |
| **Organismos del sector público deben aceptar el wallet** | **6 dic 2026** | Sector público |
| **VLOPs** (plataformas muy grandes, vía DSA) deben aceptarlo | Al ofrecerse el primer wallet → dic 2026 / inicios 2027 | VLOPs |
| **⭐ Partes privadas reguladas (banca, servicios financieros) deben aceptarlo** | **6 dic 2027** (36 meses tras los actos) | Sector privado regulado |

> 🟡 Estas fechas provienen de análisis de bufete, no del texto de EUR-Lex, porque la página oficial de la Comisión no fue accesible en esta sesión (`PROVENANCE_REQUIRED`). El propio análisis señala que Alemania anticipa disponibilidad real "a inicios de 2027" — es decir, **hay riesgo de deslizamiento** entre la fecha legal y la operativa. Contrastar contra [EUR-Lex, Reglamento (UE) 2024/1183](https://eur-lex.europa.eu/eli/reg/2024/1183/oj).

**⭐ La fecha que importa para este producto es el 6 de diciembre de 2027.** Es el momento en que los clientes B2B del middleware (bancos y entidades financieras de la UE) pasan de "pueden" a "deben" aceptar el EUDI Wallet. Un middleware que en esa fecha no soporte presentación de credenciales de wallet queda funcionalmente incompleto para el mercado europeo. El horizonte de desarrollo efectivo es 2026–H1 2027.

### A.5.3 Architecture Reference Framework (ARF) 🔄 ✅

**Versión vigente: ARF v3.0.0, publicada el 23 de julio de 2026.**

Historial reciente:

| Versión | Fecha | Cambios destacados |
|---|---|---|
| **v3.0.0** | **23 jul 2026** | Alineación con los Reglamentos de Ejecución **modificados**; introduce el **Functional Conformance Assessment Framework**; soporte tanto de *Trusted Lists* como de *Lists of Trusted Entities*; **interacciones wallet-a-wallet**; *relying party services* |
| v2.9.0 | 21 may 2025 | Navegación de conformidad funcional; documentos de discusión temas C, E, J, X |
| v2.8.0 | 2 feb 2025 | Fusión con docs.dev.eudi; temas E, AA, T |
| v2.7.x | nov 2024 | Correcciones y papeles de discusión |

> ⚠️ El ARF es explícitamente un documento de trabajo *"with no legal value"*; lo vinculante son el Reglamento y sus actos de ejecución. El ARF define **cómo** implementar de forma interoperable.

### A.5.4 Pila técnica exigida ✅

| Capa | Estándar | Rol |
|---|---|---|
| **Formato de credencial (ISO)** | **ISO/IEC 18013-5:2021** — mDoc / mDL | Formato CBOR; base del PID en modo mDoc; también mDL |
| **Formato de credencial (IETF)** | **SD-JWT VC** (*Selective Disclosure JWT Verifiable Credential*) | Formato JSON con divulgación selectiva |
| **Modelo de datos W3C** | W3C Verifiable Credentials Data Model 1.1 | Admitido |
| **Presentación remota** | **OpenID4VP** (OpenID for Verifiable Presentations) | Protocolo de solicitud/presentación de credenciales — **es la interfaz que el middleware debe implementar como Relying Party** |
| **Emisión** | **OpenID4VCI** (OpenID for Verifiable Credential Issuance) | Recomendado para emisión de atestaciones |
| **Codificación PID** | **CBOR y JSON** ambos requeridos para atestaciones PID; JSON-LD admisible para EAA no cualificadas | — |
| **Confianza** | **Trusted Lists** + 🔄 **Lists of Trusted Entities** (nuevo en v3.0.0) + PKI y validación basada en certificados | Verificación del estatus de los participantes del ecosistema |

**Consecuencia arquitectónica.** El EUDI Wallet **no es "otro método de KYC"** que se suma a la lista: es un modelo distinto. En el flujo actual el middleware **captura y procesa** (documento + selfie + matching + PAD). En el flujo EUDI el middleware **solicita y verifica una presentación criptográfica** — no hay biometría que capturar ni MRZ que leer, porque la verificación de identidad ya la hizo el emisor del PID y viaja firmada. Requiere:
- Un **rol de Relying Party registrado**, con certificado de acceso y registro en la lista correspondiente
- Implementación de **OpenID4VP** como verificador
- Parsers **duales**: mDoc/CBOR (ISO 18013-5) **y** SD-JWT VC
- Validación contra **Trusted Lists** / *Lists of Trusted Entities*
- Soporte de **divulgación selectiva** y respeto del principio de minimización (pedir sólo los atributos necesarios — es una obligación reforzada del Reglamento, no una buena práctica)

**Fuentes A.5**
- [EUDI ARF — sitio oficial](https://eudi.dev/) · [Repositorio ARF y releases (v3.0.0, 23 jul 2026)](https://github.com/eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework/releases)
- [Baker McKenzie — EUDI Wallet Harmonizes Identification and Age-Gating (mar 2026)](https://www.bakermckenzie.com/en/insight/publications/2026/03/european-union-eudi-wallet-harmonizes-identification-and-age-gating)
- [Reglamento de Ejecución (UE) 2024/2977 — EUR-Lex](https://eur-lex.europa.eu/eli/reg_impl/2024/2977/oj/eng/pdf)

---

# B. PROTECCIÓN DE DATOS

## B.6 — GDPR (Reglamento (UE) 2016/679)

### B.6.1 Artículo 9 — Datos biométricos como categoría especial

**Cita normativa (Art. 9.1):** prohíbe el tratamiento de *"datos biométricos dirigidos a identificar de manera unívoca a una persona física"*.

⚠️ **Matiz técnico decisivo y frecuentemente mal aplicado:** el Art. 9 **no cubre todo dato biométrico**, sino el tratado *con la finalidad de identificar unívocamente*. La consecuencia práctica para este producto:

| Operación del middleware | ¿Art. 9? |
|---|---|
| Comparación facial **1:1** selfie ↔ foto del documento, para verificar identidad | **Sí** — finalidad de identificación unívoca |
| Búsqueda **1:N** contra base de enrolados (antifraude, detección de duplicados) | **Sí**, y además con carga de justificación mayor |
| Detección de vida (**PAD**) que sólo decide "vivo / no vivo" sin extraer plantilla identificativa | Discutible; defendible como **fuera** del Art. 9 si no genera plantilla ni permite identificación — pero **las autoridades de control tienden a interpretación amplia** 🟡 |

**Bases de licitud aplicables (excepciones del Art. 9.2):** en la práctica del onboarding financiero europeo sólo son manejables:
- **Art. 9.2(a)** — consentimiento **explícito**. Es la vía habitual, pero frágil: si el titular no puede acceder al servicio sin dar biometría, el consentimiento puede considerarse **no libre**, especialmente si no se ofrece una alternativa no biométrica.
- **Art. 9.2(g)** — interés público esencial con base en Derecho de la Unión o nacional. Es la vía más sólida cuando existe una norma AML/KYC nacional que **exige** la verificación — pero requiere que esa norma exista y sea suficientemente específica.

> ⚠️ Jurisprudencia y práctica sancionadora reciente en la UE apuntan a que **la finalidad antifraude, por sí sola, no legitima automáticamente el tratamiento biométrico** bajo el Art. 9. El análisis debe hacerse por jurisdicción y por caso de uso. 🟡

### B.6.2 Artículo 28 — El encargado del tratamiento ⭐ (núcleo del modelo B2B)

Este es **el artículo estructural del producto**: el middleware es **encargado**, y sus clientes financieros son **responsables**. Obligaciones no negociables:

| Requisito Art. 28 | Traducción a producto |
|---|---|
| **Contrato o acto jurídico vinculante (DPA)** por escrito con cada cliente | Plantilla de DPA estándar, no opcional. Debe fijar objeto, duración, naturaleza, finalidad, tipo de datos y categorías de interesados |
| Tratar los datos **únicamente siguiendo instrucciones documentadas** del responsable | Prohibición de reutilizar datos biométricos de un cliente para entrenar modelos, hacer benchmarking o construir bases antifraude compartidas **salvo instrucción o acuerdo expreso**. Este es el punto de fricción más común en eKYC |
| **Confidencialidad** del personal autorizado | Compromisos de confidencialidad documentados |
| **Art. 32** — medidas de seguridad | Cifrado en tránsito y reposo, control de acceso, registro de auditoría, pruebas de vulnerabilidad |
| **Subencargados** — autorización previa (específica o general con derecho de objeción) | Registro público de subencargados. Un proveedor de matcher facial o de OCR **es subencargado** y debe declararse |
| **Asistir al responsable** en derechos de los interesados y en brechas | Endpoints/API de acceso, rectificación y supresión; SLA de notificación de brecha compatible con las 72 h del responsable (en la práctica ≤24 h) |
| **Suprimir o devolver** los datos al final del servicio | Procedimiento de terminación con certificado de borrado, incluidos backups |
| Poner a disposición la información necesaria para demostrar cumplimiento y **permitir auditorías** | Derecho de auditoría o informes de tercero (SOC 2 / ISO 27001) como sustitutivo pactado |

> ⚠️ Un encargado que determina por su cuenta finalidades o medios esenciales **deja de ser encargado y pasa a ser corresponsable (Art. 26)**, asumiendo responsabilidad directa. Entrenar modelos con datos de clientes sin instrucción es la vía más rápida a esa reclasificación.

### B.6.3 Artículo 25 — Privacidad desde el diseño y por defecto

Traducción concreta a un middleware biométrico:
- **Minimización:** no persistir el vídeo completo de la sesión si basta con un frame y el resultado; no almacenar la plantilla biométrica si el caso de uso es una verificación puntual 1:1
- **Efímero por defecto:** el modo de operación por defecto debería ser *stateless* — procesar, devolver veredicto, destruir. La retención debe ser una **opción activada por el responsable**, no el default
- **Seudonimización** y separación lógica de la plantilla biométrica respecto de los identificadores
- **Multi-tenancy con aislamiento estricto** entre clientes: los datos de un responsable no pueden mezclarse con los de otro (refuerza además el Art. 28)

### B.6.4 Artículo 35 — DPIA obligatoria

La **EIPD/DPIA es obligatoria** en este escenario: concurren simultáneamente varios criterios de alto riesgo (datos de categoría especial del Art. 9, tratamiento a gran escala, uso de tecnología innovadora, evaluación/scoring, y en 1:N tratamiento sistemático). El **EDPB** estableció criterios comunes y las autoridades nacionales publicaron **listas de tratamientos que requieren DPIA**, en las que el tratamiento biométrico a gran escala figura de forma recurrente.

> ⚠️ **Punto de reparto de responsabilidades:** la DPIA es obligación **del responsable** (el banco), no del encargado. Pero el Art. 28 obliga al encargado a **asistirle**. En la práctica comercial, entregar un **paquete de DPIA** (descripción del tratamiento, flujos de datos, medidas técnicas, métricas APCER/BPCER/FMR/FNMR, análisis de sesgo demográfico, subencargados, ubicaciones) es un requisito de facto para vender a entidades europeas. Es diferenciador comercial además de obligación legal.

### B.6.5 Artículo 17 — Derecho de supresión

Se trata en el apartado C.11, por su tensión con la retención AML.

### B.6.6 Transferencias internacionales (Cap. V) ⭐ crítico para una arquitectura LATAM+UE

| País | Decisión de adecuación de la Comisión Europea |
|---|---|
| **México** | **No** |
| **Bolivia** | **No** |
| **Paraguay** | **No** |

Ninguno de los tres países LATAM del alcance tiene decisión de adecuación. Consecuencias operativas:

1. Toda transferencia de datos personales UE → BO/PY/MX requiere **garantías adecuadas**: en la práctica, **Cláusulas Contractuales Tipo (SCC)** (Decisión de Ejecución (UE) 2021/914), módulo **Encargado→Subencargado** o **Responsable→Encargado** según el caso.
2. **Transfer Impact Assessment (TIA)** obligatorio por cada destino, evaluando el marco de acceso gubernamental a los datos en Bolivia, Paraguay y México.
3. **Recomendación arquitectónica fuerte:** **regionalizar el procesamiento**. Datos de titulares UE se procesan y almacenan en la UE; datos LATAM en LATAM. Esto elimina la mayor parte del problema de Cap. V, simplifica el TIA, y resuelve de paso los requisitos de localización/soberanía que los reguladores financieros latinoamericanos tienden a imponer. El coste de un despliegue multi-región es sensiblemente menor que el de sostener SCC + TIA para datos biométricos de categoría especial.
4. **Atención al soporte técnico:** el acceso remoto desde LATAM a datos alojados en la UE **es una transferencia internacional**, aunque los datos no se muevan. Debe cubrirse en SCC y controlarse.

**Fuentes B.6**
- [Reglamento (UE) 2016/679 (GDPR) — EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [EDPB — Directrices 3/2019 sobre tratamiento de datos personales mediante dispositivos de vídeo (incluye análisis de biometría y Art. 9)](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_201903_video_devices_es.pdf)
- [IAPP — What's subject to a DPIA under the GDPR? EDPB on draft lists of 22 supervisory authorities](https://iapp.org/news/a/whats-subject-to-a-dpia-under-the-gdpr-edpb-on-draft-lists-of-22-supervisory-authorities)
- [ICO — When do we need to do a DPIA?](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/accountability-and-governance/data-protection-impact-assessments-dpias/when-do-we-need-to-do-a-dpia/)

---

## B.7 — MÉXICO: LFPDPPP 🔄🔄 (doble cambio en 2025 y 2026)

### B.7.1 Nueva LFPDPPP — 🔄 CAMBIO ESTRUCTURAL ✅

| Dato | Valor |
|---|---|
| **Publicación en el DOF** | **20 de marzo de 2025** |
| **Entrada en vigor** | **21 de marzo de 2025** (al día siguiente) |
| **Naturaleza** | **Ley nueva que abroga la LFPDPPP de 2010** — no es una reforma |
| **Autoridad** | 🔄 **Secretaría Anticorrupción y Buen Gobierno**, en sustitución del **INAI** (extinguido) |
| **Reglamento** | ❌ **No verificado que se haya publicado el reglamento de la nueva ley.** Fuentes secundarias de 2026 lo describen como **pendiente**, lo que deja zonas de incertidumbre operativa 🟡 |

### B.7.2 Datos biométricos: ⚠️ HALLAZGO CONTRAINTUITIVO

**La nueva LFPDPPP de 2025 NO incorporó expresamente los datos biométricos al catálogo de datos personales sensibles.**

La definición de datos sensibles se mantiene como aquellos *"que afectan la esfera más íntima del titular"*, con enumeración de origen racial o étnico, estado de salud, información genética, creencias religiosas, filosóficas y morales, afiliación sindical, opiniones políticas y preferencia sexual. R3D (organización que litigó y analizó la reforma) señala expresamente que la nueva ley *"no reconoce la protección especial de los datos biométricos, genéticos y de geolocalización"* y que **no actualizó definiciones clave como la de dato sensible** — calificándolo como oportunidad perdida.

> ⚠️ **Cómo tratar esto en la práctica.** Que la ley no los liste **no significa que no sean sensibles**. La vía sigue siendo la interpretación finalista: si el dato biométrico revela información de la esfera íntima o se usa para identificación unívoca, encaja en la cláusula general. El INAI, antes de su extinción, sostuvo en su [Guía para el Tratamiento de Datos Biométricos](https://inicio.inai.org.mx/DocumentosdeInteres/GuiaDatosBiometricos_Web_Links.pdf) que los biométricos pueden ser sensibles según contexto y finalidad.
>
> **Recomendación de diseño:** tratar los datos biométricos **como sensibles en México por defecto** (consentimiento expreso y por escrito, finalidades acotadas, medidas reforzadas). El coste de sobrecumplir es marginal; el riesgo de la interpretación contraria por la nueva autoridad — con criterios aún no consolidados — es alto. Además, el estándar sensible ya es exigible por GDPR y por Paraguay, de modo que un diseño único y uniforme es más simple que uno diferenciado por país.

### B.7.3 Consentimiento y aviso de privacidad 🟡

- **Consentimiento:** puede ser **expreso** (verbal, escrito o por medios electrónicos) o **tácito** cuando el titular no manifiesta oposición tras recibir el aviso de privacidad.
- **Datos sensibles:** el estándar histórico de la LFPDPPP 2010 (art. 9) era **consentimiento expreso y por escrito**, con firma autógrafa, electrónica o cualquier mecanismo de autenticación. ❌ **NO VERIFICADO en el texto de la ley de 2025** que se mantenga esta redacción exacta — no pude descargar el texto oficial (`diputados.gob.mx` devolvió error de permisos y el DOF está bloqueado por robots.txt). **Verificar antes de diseñar el flujo de consentimiento.**
- **Aviso de privacidad:** debe identificar los datos sensibles y las finalidades; puede difundirse en *"formatos impresos, digitales, visuales, sonoros o cualquier otra tecnología"*.
- **Encargado:** la figura se mantiene y sus obligaciones están reguladas.

### B.7.4 🔄🔄 CNBV — Reforma biométrica de julio de 2026 (el cambio más reciente y más relevante)

| Dato | Valor | Verif. |
|---|---|---|
| **Publicación en el DOF** | **1 de julio de 2026** | 🟡 |
| **Entrada en vigor** | **2 de julio de 2026** | 🟡 |
| **Norma modificada** | Disposiciones de carácter general aplicables a las instituciones de crédito (**CUB**), en materia de identificación de usuarios y operaciones presenciales; **sustituye el Anexo 71** | 🟡 |
| **Plazo de implementación** | **90 días hábiles** máximo para los bancos | 🟡 |

**Contenido sustantivo:**
- Se **incorpora expresamente la biometría facial** como método de verificación de identidad, **adicional a la huella dactilar**
- La información biométrica *"deberá utilizarse exclusivamente para fines de autenticación de identidad"*
- **Umbral de coincidencia:** ⚠️ **fuentes en conflicto** — una fuente indica **coincidencia mínima del 90 %** en verificación en línea (Basham, bufete); otra indica **98 %** (proveedor). ❌ **NO RESUELTO.** Debe verificarse en el texto del DOF del 1/07/2026. Es un parámetro que va directo a la configuración del producto, así que no debe asumirse.
- **Contraste obligatorio** contra registros de **INE, SRE, SAT** u otras autoridades competentes con servicios de verificación biométrica
- Los bancos **pueden** construir bases de datos biométricas propias, **pero sólo tras validar** contra registros oficiales
- **Prohibición expresa** de comercializar, enajenar o transferir bases de datos biométricas entre instituciones de crédito o a terceros
- **Controles exigidos:** infraestructura dedicada, cifrado, control de accesos, **bitácoras de auditoría**, pruebas de vulnerabilidad, mecanismos de prevención de fraude de identidad
- **Ámbito:** operaciones **presenciales** de cuentas Nivel 4 (pasivas) y operaciones activas/servicios/medios de pago Nivel 3–4

**Onboarding NO presencial (régimen preexistente)** 🟡:
- Base normativa: **artículos 51 Bis 6 a 51 Bis 9** de las Disposiciones + **Anexo 71**
- Captura de identificación oficial **anverso y reverso**, verificación de elementos de seguridad y **cotejo contra la autoridad emisora**
- **Prueba de vida certificada**, con capacidad de detectar ***deepfakes*, máscaras, fotos estáticas y ataques de inyección**
- Conservación del registro del proceso *"íntegra y sin ediciones"*
- Aplica a cuentas **Nivel 4**, créditos al consumo y comerciales
- Antecedente: resolución del **15 de agosto de 2024** que introdujo la disposición **4ª Ter**, ampliando el régimen de identificación remota y exigiendo, para Nivel 4, *"verificar la coincidencia de la información biométrica del Cliente"* contra registros de autoridades mexicanas o bases propias

> ⚠️ La prohibición de **transferir bases de datos biométricas a terceros** tiene consecuencia directa sobre la arquitectura del middleware en México: **el proveedor no puede constituirse en depositario de las plantillas biométricas del banco ni operarlas como base compartida entre clientes**. El modelo viable es de **procesamiento por cuenta del banco, con la base residiendo bajo control del banco** (o, como mínimo, lógicamente segregada y jurídicamente atribuida a él). Un diseño de "base antifraude multi-cliente" es difícilmente compatible con esta norma.
>
> ⚠️ Nótese también la asimetría: la exigencia de **detección de ataques de inyección** en el régimen no presencial va **más allá del alcance de ISO/IEC 30107-3**. Una certificación iBeta Level 1/2 **no acredita por sí sola** el cumplimiento de este requisito mexicano.

**Fuentes B.7**
- [Garrigues — México: la nueva LFPDPPP introduce el aviso de privacidad y elimina el INAI](https://www.garrigues.com/es_ES/noticia/mexico-nueva-ley-federal-proteccion-datos-personales-posesion-particulares-introduce)
- [R3D — Las nuevas leyes de transparencia y protección de datos personales: retrocesos y oportunidades perdidas](https://r3d.mx/2025/03/21/las-nuevas-leyes-de-transparencia-y-proteccion-de-datos-personales-retrocesos-y-oportunidades-perdidas/)
- [Greenberg Traurig — Alerta: Nueva LFPDPPP (PDF)](https://www.gtlaw.com/-/media/files/insights/alerts/2025/3/alerta-gt_nueva-ley-federal-de-proteccion-de-datos-personales-en-posesion-de-los-particulares.pdf)
- [EY México — Entrada en vigor de la nueva LFPDPPP](https://www.ey.com/es_mx/technical/tax/boletines-fiscales/nueva-ley-federal-proteccion-datos-personal-posesion-particulares)
- [Basham — Resolución que modifica las Disposiciones aplicables a las instituciones de crédito (1 jul 2026)](https://basham.com.mx/resolucion-que-modifica-las-disposiciones-de-caracter-general-aplicables-a-las-instituciones-de-credito/)
- [IDC — CNBV: ¿Los bancos almacenarán tu rostro y huellas? (7 jul 2026)](https://idconline.mx/corporativo/2026/07/07/cnbv-los-bancos-almacenaran-tu-rostro-y-huellas)
- [SIDOF — Resolución de 15 de agosto de 2024 (disposiciones art. 115 LIC)](https://sidof.segob.gob.mx/notas/docFuente/5737473)
- [CNBV — Disposiciones aplicables a las instituciones de crédito (texto)](https://www.cnbv.gob.mx/Normatividad/Disposiciones%20de%20car%C3%A1cter%20general%20aplicables%20a%20las%20instituciones%20de%20cr%C3%A9dito.pdf)

---

## B.8 — BOLIVIA

### B.8.1 Protección de datos personales: ❌ NO EXISTE LEY INTEGRAL VIGENTE

**Conclusión verificada: a agosto de 2026, Bolivia NO cuenta con una ley general de protección de datos personales en vigor.** Lo que existe es un **anteproyecto** impulsado por **AGETIC** (Agencia de Gobierno Electrónico y Tecnologías de Información y Comunicación), publicado en su versión 2024 y difundido en 2025, más un anteproyecto alternativo de la sociedad civil (Internet Bolivia / campaña "Mis Datos"). Ninguno ha sido sancionado como ley.

**Marco fragmentario efectivamente aplicable:**

| Instrumento | Contenido |
|---|---|
| **Constitución Política del Estado, art. 21.2 y art. 130** | Derecho a la privacidad e intimidad; **acción de protección de privacidad** (*habeas data* boliviano) |
| **Ley 164 (Telecomunicaciones y TIC)** y su reglamento | Disposiciones dispersas sobre datos en servicios de telecomunicaciones y documento digital |
| **Ley 393 de Servicios Financieros, art. 74.I.f** | Derecho del consumidor financiero *"A la confidencialidad, con las excepciones establecidas por Ley"* ✅ |
| **Ley 393, art. 29.II** | *"La información que sea requerida por medios electrónicos, con respaldo de firmas electrónicas, tendrá plena validez y fuerza probatoria para todos los efectos"* ✅ — habilitación general de la contratación digital |
| **Ley 393, art. 34.III** | Conservación de libros y documentos *"por un período no menor a diez (10) años, desde la fecha del último asiento contable"*, admitiendo microfilm o medios magnéticos/electrónicos ✅ |

> ⚠️ **Riesgo estratégico, no oportunidad.** La ausencia de ley no es "menos carga regulatoria": es **incertidumbre**. Cuando la ley se apruebe (el anteproyecto sigue el modelo GDPR/Convenio 108+), lo hará probablemente con un período de adecuación corto y con la biometría clasificada como dato sensible. Un diseño que hoy se relaje en Bolivia tendrá que rehacerse. **Recomendación: aplicar en Bolivia el mismo estándar técnico que en la UE** — coste marginal cero si el producto es único, y elimina el riesgo de retrofit.

### B.8.2 Normativa financiera: ASFI y UIF

**Marco institucional.** Dos reguladores concurren: **ASFI** (Autoridad de Supervisión del Sistema Financiero), que emite la **Recopilación de Normas para Servicios Financieros (RNSF)**, y la **UIF** (Unidad de Investigaciones Financieras), que emite los **Instructivos Específicos** en materia LGI/FT-DP para entidades de intermediación financiera (EIF).

**Debida diligencia del cliente — Instructivo UIF vigente** ✅ (Instructivo EIF, R.A. N° 16, marzo 2026):

| Artículo | Contenido |
|---|---|
| **Art. 33(a)** | *"procedimientos de identificación al inicio y durante la relación comercial"* |
| **Art. 33(b)** | *"procedimientos de verificación al inicio y durante la relación comercial"* |
| **Art. 33(c)** | *"actividades permanentes de monitoreo y evaluación de las transacciones"* |
| **⚠️ Art. 32(II)** | ***"El Sujeto Obligado no podrá delegar a terceros la ejecución de las medidas de Debida Diligencia del cliente"*** |
| **Art. 34.IV** (instructivo previo R.A. 42/2022) | Obligación de *"consultar con el Servicio General de Identificación Personal (SEGIP) a través del sistema establecido"* |

> ⚠️⚠️ **El artículo 32(II) es el hallazgo de mayor impacto comercial de toda esta investigación para Bolivia.** La prohibición de **delegar la ejecución de la DDC a terceros** exige un posicionamiento contractual muy cuidadoso: el middleware debe articularse como **herramienta tecnológica que la entidad utiliza para ejecutar por sí misma su DDC**, nunca como un servicio al que la entidad *externaliza* la debida diligencia. Esto tiene consecuencias concretas:
> - El **veredicto de aceptación/rechazo del cliente debe ser tomado por la EIF**, no por el middleware. El producto entrega **señales y evidencias** (coincidencia biométrica, validez documental, resultado PAD), no una decisión de onboarding vinculante.
> - Debe existir un **paso de decisión bajo control de la entidad**, aunque esté automatizado por reglas que ella configura.
> - El lenguaje contractual y de marketing debe evitar términos como "realizamos su KYC" en el mercado boliviano.
>
> ❌ **NO VERIFICADO:** si la ASFI o la UIF han emitido criterio interpretativo que module el art. 32(II) respecto de proveedores tecnológicos. **Es la consulta regulatoria prioritaria antes de entrar en Bolivia.**

**Onboarding digital / no presencial: ❌ VACÍO NORMATIVO**

Búsquedas repetidas en normativa ASFI y UIF **no localizaron ningún reglamento que autorice, regule o establezca requisitos para la identificación no presencial, la verificación biométrica remota o la prueba de vida** en entidades financieras bolivianas.

Lo verificado:
- El Instructivo UIF **no menciona explícitamente** procedimientos de onboarding digital ni verificación biométrica; **enfatiza la identificación presencial** mediante documento físico (Cédula de Identidad) consultado al SEGIP ✅
- El **Reglamento para Empresas de Tecnología Financiera (ETF)**, aprobado por **Resolución ASFI/540/2025 del 3 de julio de 2025** ✅, crea un régimen de constitución y funcionamiento de ETF y un **Entorno Controlado de Pruebas (ECP)** — un *sandbox* regulatorio que permite probar servicios *"en condiciones reales, limitadas y controladas"* con flexibilidad regulatoria. Impone obligaciones de *"protección de datos personales, ciberseguridad, tratamiento de información, atención de reclamos y gestión de riesgos"*, **pero no detalla requisitos de onboarding digital, identificación remota ni biometría**. Plazo de inicio de adecuación: **31 de diciembre de 2025**
- Norma habilitante superior: **Decreto Supremo N° 5384, de 7 de mayo de 2025**, que reglamenta la constitución y funcionamiento de las ETF ✅

> **Lectura estratégica.** Bolivia combina (i) ausencia de ley de datos, (ii) ausencia de marco de onboarding remoto, (iii) prohibición de delegar DDC, y (iv) un sandbox recién creado. El camino de entrada más razonable es **vía el ECP de ASFI**, que es precisamente el mecanismo diseñado para operar sin marco específico. Entrar por la vía ordinaria sin cobertura normativa expresa deja a la entidad cliente expuesta.
>
> ❌ **NO VERIFICADO:** el plazo de conservación de registros del Instructivo UIF. Su art. 39(VII) remite al **art. 66** para *"las condiciones y el plazo"*, pero el art. 66 no fue recuperable del PDF. El plazo de **10 años** del art. 34.III de la Ley 393 aplica a libros y documentos contables y es el suelo razonable, pero **no confirmé que sea el plazo del expediente KYC**.

**Fuentes B.8**
- [AGETIC — Anteproyecto de Ley de Protección de Datos Personales 2024 (presentación)](https://agetic.gob.bo/sites/default/files/2025-06/DATOS-PERSONALES-PRESENTACION-ANTEPROYECTO-DE-LEY-2024-firmado.pdf) · [Manual de Protección de Datos](https://agetic.gob.bo/sites/default/files/2025-06/Manual-de-Proteccion-de-Datos-2-firmado.pdf)
- [Internet Bolivia — campaña "Mis Datos" y anteproyecto alternativo](https://misdatos.internetbolivia.org/) · [Guía de implementación (PDF)](https://internetbolivia.org/wp-content/uploads/2025/05/guia_proteccion_datos_web.pdf)
- [Ley 393 de Servicios Financieros — texto ordenado (ASFI)](https://www.asfi.gob.bo/sites/default/files/2025-07/Texto%20ordenado.pdf)
- [ASFI — Recopilación de Normas para Servicios Financieros (RNSF)](https://www.asfi.gob.bo/la/recopilacion-normas-para-servicios-financieros-rnsf)
- [ASFI — Reglamento para Empresas de Tecnología Financiera (Res. ASFI/540/2025)](https://www.asfi.gob.bo/index.php/node/1176)
- [Decreto Supremo N° 5384 de 7 de mayo de 2025](https://www.asfi.gob.bo/sites/default/files/2025-08/Decreto%20Supremo%20N%C2%B0%205384%20de%20fecha%207%20de%20mayo%20de%202025.pdf)
- [UIF Bolivia — Instructivo EIF R.A. N° 16 (2026)](https://www.uif.gob.bo/wp-content/uploads/2026/03/INSTRUCTIVO-EIF-R.A.-No.-16-1.pdf) · [Normativa externa UIF](https://www.uif.gob.bo/index.php/normativa-externa/)

---

## B.9 — PARAGUAY

### B.9.1 🔄 Ley N° 7593/2025 — SÍ HAY LEY INTEGRAL (nueva, en vacatio legis)

**Cambio de primer orden: Paraguay aprobó su primera ley integral de protección de datos personales.**

| Dato | Valor | Verif. |
|---|---|---|
| **Norma** | **Ley N° 7593/2025, "De Protección de Datos Personales en la República del Paraguay"** | ✅ |
| **Promulgación** | **27–28 de noviembre de 2025** (fuentes dan 27 y 28; el Ejecutivo la promulgó el 28 según prensa) | 🟡 |
| **Vacatio legis** | **24 meses** — exigibilidad general en torno a **noviembre de 2027** | 🟡 |
| **Reglamentación** | El Ejecutivo dispone de **24 meses** para dictar la reglamentación | 🟡 |
| **Autoridad** | 🆕 **Agencia Nacional de Protección de Datos Personales (ANDP)**, unidad descentralizada bajo el **MITIC** con independencia funcional; competencia exclusiva regulatoria, de supervisión y sancionadora | 🟡 |

**⚠️ Precisión sobre la Ley 6534:** la Ley **6534/2020** es de **protección de datos personales crediticios** — un régimen sectorial de burós de crédito, **no una ley general**. Fue la norma citada durante años como "la ley paraguaya de datos", pero **no cubría biometría ni tratamiento general**. La Ley 7593/2025 es la que instaura el régimen integral. Confundirlas es un error frecuente en documentación comercial.

**Contenido relevante para el producto:** 🟡

| Materia | Disposición |
|---|---|
| **Datos sensibles** | Incluyen expresamente **datos biométricos y genéticos**, junto a origen racial/étnico, creencias religiosas, afiliación política, salud y orientación sexual ⭐ |
| **Ámbito extraterritorial** | Aplica a tratamientos de establecidos en Paraguay **y** a quienes dirijan servicios a residentes paraguayos o **monitoreen su comportamiento**, con independencia de dónde estén los datos — **modelo GDPR** |
| **Menores** | Protección especial para **menores de 16 años**, con consentimiento parental |
| **Bases de licitud** | Consentimiento para fines determinados; obligación legal; función pública; ejecución contractual; procedimientos judiciales/administrativos; **interés legítimo** cuando no prevalezcan los derechos del titular |
| **Encargado del tratamiento** ⭐ | Debe incluir **cláusulas de seguridad y notificación de incidentes** en el contrato de tratamiento y **facilitar auditorías del responsable** |
| **Transferencias internacionales** | Requieren nivel adecuado según la ANDP, o garantías apropiadas: **cláusulas contractuales tipo** o **normas corporativas vinculantes** |
| **Derecho de supresión** | Plazo de respuesta: **30 días hábiles**; excepciones por **obligación legal** o interés legítimo ⭐ |
| **EIPD** | Obligatoria para tratamientos de alto riesgo con **decisiones automatizadas** o **monitoreo sistemático** que afecte derechos fundamentales |
| **Brechas** | Notificación en **72 horas** |
| **Derechos** | Acceso, rectificación, supresión, portabilidad |
| **Sanciones** | De **20 a 2.500 jornales mínimos** (datos generales); hasta **5.000** (datos sensibles); hasta **10.000** (datos sensibles de menores). A julio de 2026, el máximo equivale a ~**Gs. 1.170 millones** |

> ⭐ **Implicación de producto:** Paraguay pasa de ser la jurisdicción más laxa de las tres a tener un régimen **funcionalmente equivalente al GDPR**, incluida la clasificación expresa de biometría como dato sensible, obligaciones específicas del encargado, EIPD y transferencias con SCC. **El diseño GDPR-compliant del middleware sirve para Paraguay casi sin adaptación.** La ventana de adecuación (hasta ~nov-2027) coincide aproximadamente con la del EUDI Wallet: **es el mismo ciclo de trabajo**.

### B.9.2 Normativa AML: SEPRELAD y BCP

**Reparto de competencias.** La **SEPRELAD** (Secretaría de Prevención de Lavado de Dinero o Bienes) dicta las resoluciones aplicables a los sujetos obligados **supervisados por el BCP** (bancos, financieras, casas de cambio); el **BCP** regula el producto y las cuentas.

**Resolución SEPRELAD N° 70/2019** (modificada por Res. 254/2020 en sus arts. 26, 27 y 28) ✅:

| Artículo | Contenido |
|---|---|
| **Art. 25** — Régimen general de DDC | Datos mínimos: nombres completos, documento de identidad, nacionalidad, domicilio, teléfono/email, ocupación, **declaración jurada del origen de fondos** y documentación de ingresos. Personas jurídicas: razón social, RUC, escritura de constitución, nómina de socios/accionistas con participación **>10 %**, y datos de representantes legales |
| **Art. 26** — Régimen simplificado | Para riesgo LA/FT bajo: nombres, documento, nacionalidad, domicilio y ocupación. Requiere formulario de identificación con documentación de respaldo |
| **Art. 28** — Régimen ampliado | Obligatorio para personas jurídicas no domiciliadas, fideicomisos, OSFL, **PEP**, transferencias a países no cooperantes y demás alto riesgo |
| **Art. 24(b)** | Permite iniciar la relación antes de completar la verificación, con plazos |
| **Arts. 40 y 59** | Exigen *"sistemas de información"* y *"medios tecnológicos"* **genéricos** — sin mencionar biometría |
| **Art. 42** | Conservación: **cinco (5) años** *"contados a partir de la finalización de la relación comercial"* o desde la operación ocasional |
| **Art. 43** | Información del sistema de prevención: **cinco (5) años** desde la finalización de la relación o la fecha de la transacción |

**Ley N° 1015/1997** (modificada por Leyes 3783/2009 y 6497/2019), **art. 18**: *"Los sujetos obligados deberán conservar durante un período de cinco años los registros de las operaciones y las medidas de debida diligencia que implementen"* ✅

**Onboarding no presencial: ❌ VACÍO NORMATIVO (igual que Bolivia)**

La Resolución 70/2019 **no regula expresamente las relaciones no presenciales ni el onboarding digital**, y **no menciona biometría**. Se localizó el **Reglamento de las Cuentas Básicas de Ahorro** (Resolución BCP N° 5, Acta 13, del 4 de abril de 2024), que es el instrumento más próximo a un régimen de cuentas de apertura simplificada, pero ❌ **no verifiqué su contenido en materia de identificación remota**.

> ⚠️ **Riesgo idéntico al boliviano:** ausencia de habilitación expresa para la identificación remota. La diferencia es que Paraguay **sí** tiene ahora ley de datos, de modo que el tratamiento biométrico está regulado aunque el onboarding remoto no lo esté. El resultado es la peor combinación posible si no se gestiona: **obligaciones de protección de datos plenas sin cobertura normativa sectorial que justifique el tratamiento**. Refuerza la necesidad de apoyar la licitud en el consentimiento explícito y en el enfoque basado en riesgo del GAFI, y de consultar a SEPRELAD/BCP.
>
> ❌ **PENDIENTE:** verificar si SEPRELAD o el BCP han emitido resoluciones posteriores a 2020 sobre identificación no presencial. La búsqueda no las localizó, pero el índice de resoluciones vigentes del BCP no fue revisado exhaustivamente.

**Fuentes B.9**
- [BACN — Ley N° 7593/2025 de Protección de Datos Personales](https://www.bacn.gov.py/leyes-paraguayas/12924/ley-n-7593-2025-de-protecci-n-de-datos-personales-en-la-rep-blica-del-paraguay)
- [Avanzia Legal — Guía de cumplimiento Ley 7593/2025](https://www.avanzialegal.com/blog/ley-7593-2025-proteccion-datos-personales-empresas)
- [BKM/Berke — Análisis de la Ley N° 7593/2025](https://www.berke.com.py/analisis-de-la-ley-n-7593-2025-de-proteccion-de-datos-personales-de-paraguay1/)
- [Deloitte — Nueva Ley de Protección de Datos Personales en Paraguay](https://www.deloitte.com/latam/es/services/legal/perspectives/nueva-ley-de-proteccion-de-datos-personales-en-paraguay.html)
- [La Nación — Ejecutivo promulgó la Ley de Protección de Datos Personales (28 nov 2025)](https://www.lanacion.com.py/politica/2025/11/28/ejecutivo-promulgo-la-ley-de-proteccion-de-datos-personales/)
- [Resolución SEPRELAD N° 70/2019 (texto)](https://baselegal.com.py/docs/8c9cc0ef-eac1-11e9-aeeb-525400c761ca/text) · [Resolución SEPRELAD N° 254/2020](https://baselegal.com.py/docs/658950b9-25c1-11eb-bd65-525400c761ca/text)
- [SEPRELAD — Ley 1015/1997 actualizada](https://www.seprelad.gov.py/resoluciones/resoluciones/ley10151997actualizada_.pdf)
- [BCP — Reglamento de las Cuentas Básicas de Ahorro (Res. 5, Acta 13, 04/04/2024)](https://www.bcp.gov.py/documents/20117/410942/Resolucion+5+acta+13+04-04-2024+reglamento+de+cuentas+b%C3%A1sicas+de+ahorro.pdf)
- [Ministerio Público — Resoluciones SEPRELAD aplicables a sujetos obligados supervisados por el BCP](https://denuncias.ministeriopublico.gov.py/resoluciones-de-la-seprelad-aplicables-a-los-sujetos-obligados-supervisados-por-el-bcp-)

---

## B.10 — GAFI / FATF: Recomendación 10 y Guía de Identidad Digital

### B.10.1 Recomendación 10 — Debida Diligencia del Cliente ✅

**Momentos en que se activa la DDC:**
> *"(i) establecen relaciones comerciales; (ii) realizan transacciones ocasionales por encima de USD/EUR 15.000; (iii) existe sospecha de lavado de activos o financiamiento del terrorismo; o (iv) hay dudas sobre la veracidad de datos previos."*

**Medidas exigidas:**
> *"Identificar al cliente y verificar la identidad utilizando documentos confiables"* e *"Identificar al beneficiario final y tomar medidas razonables para verificar su identidad."*

### B.10.2 Recomendación 1 — Enfoque Basado en Riesgo ✅

> *"aplicar un enfoque basado en riesgo (EBR) a fin de asegurar que las medidas para prevenir o mitigar el lavado de activos correspondan con los riesgos identificados."*

Es la **piedra angular** para el onboarding remoto: el GAFI no prescribe tecnologías, sino que la intensidad de la verificación sea proporcional al riesgo. Esto habilita niveles de cuenta escalonados (como los Niveles 1–4 mexicanos) y justifica que la verificación biométrica se exija en niveles altos y no en los básicos.

### B.10.3 Guía de Identidad Digital del GAFI (marzo 2020) ✅

Documento clave: *FATF Guidance on Digital Identity*, marzo de 2020.

**Aportaciones centrales para este producto:**

1. **La identidad digital no es intrínsecamente de mayor riesgo.** ⭐ La Guía revierte la presunción tradicional de que lo "no presencial" es automáticamente alto riesgo. Sostiene que los sistemas de identidad digital **fiables e independientemente asegurados** pueden ser **iguales o más fiables** que la verificación presencial con documentos físicos. Esta es la base argumental más importante que un middleware de eKYC puede invocar ante un regulador o un oficial de cumplimiento conservador.

2. **Marco de evaluación en dos dimensiones**, basado en los estándares técnicos de aseguramiento (explícitamente alineado con NIST SP 800-63 y equivalentes):
   - **Assurance de la prueba de identidad** (*identity proofing*) → corresponde a **IAL**
   - **Assurance de la autenticación** → corresponde a **AAL**

3. **Aseguramiento independiente.** La Guía enfatiza que el nivel de confianza debe estar **certificado o auditado por un tercero independiente**, no autodeclarado. ⭐ Esto es lo que convierte las certificaciones **iBeta/ISO 30107-3** y los informes **NIST FRTE** de argumento comercial en **evidencia regulatoria**: son precisamente el "aseguramiento independiente" que el GAFI pide.

4. **Aplicación proporcional.** Los sistemas de identidad digital con niveles de aseguramiento más bajos pueden usarse para relaciones de menor riesgo (cuentas básicas, inclusión financiera), reservando los niveles altos para relaciones de mayor riesgo.

> **Síntesis para el diseño:** la cadena argumental defendible ante cualquiera de los cuatro reguladores es:
> **R.1 (EBR)** → **Guía de ID Digital del GAFI** (lo remoto puede ser tan o más fiable) → **NIST SP 800-63A-4 IAL2** (especificación técnica del nivel de aseguramiento, con umbrales FMR ≤10⁻⁴ / FNMR ≤10⁻² / IAPAR <0,07) → **ISO/IEC 30107-3 + certificación iBeta + informe NIST FRTE** (aseguramiento independiente del cumplimiento de esos umbrales) → **R.10** satisfecha.
> Esta cadena es especialmente valiosa en **Bolivia y Paraguay**, donde no hay norma sectorial de onboarding remoto y el GAFI es el único referente disponible. Bolivia y Paraguay son miembros de **GAFILAT**, por lo que los estándares GAFI les son aplicables vía evaluación mutua.

**Fuentes B.10**
- [FATF — Guidance on Digital Identity (marzo 2020, PDF completo)](https://www.fatf-gafi.org/content/dam/fatf-gafi/guidance/Guidance-on-Digital-Identity.pdf) · [Resumen ejecutivo](https://www.fatf-gafi.org/content/dam/fatf-gafi/guidance/Guidance-on-Digital-Identity-Executive-Summary.pdf) · [Digital ID in brief](https://www.fatf-gafi.org/content/dam/fatf-gafi/brochures/Digital-ID-in-brief.pdf)
- [GAFI — Estándares Internacionales / 40 Recomendaciones (español)](https://www.fatf-gafi.org/content/dam/fatf-gafi/translations/Recommendations/FATF-40-Rec-2012-Spanish.pdf.coredownload.inline.pdf)

---

# C. RETENCIÓN Y SU CONFLICTO CON EL DERECHO DE SUPRESIÓN

## C.11.1 Plazos de conservación por jurisdicción

| Jurisdicción | Plazo | Cómputo | Fuente normativa | Verif. |
|---|---|---|---|---|
| **GAFI (estándar internacional)** | **≥ 5 años** | Desde la terminación de la relación comercial (expedientes DDC) o desde la transacción (registros de operaciones) | Recomendación 11 | ✅ |
| **PARAGUAY** | **5 años** | Desde la finalización de la relación comercial o la operación ocasional | Res. SEPRELAD 70/2019, **arts. 42 y 43**; Ley 1015/1997, **art. 18** | ✅ |
| **MÉXICO** | **10 años** (ampliamente citado) | Desde la terminación de la relación / celebración de la operación | Disposiciones de carácter general art. 115 LIC | ❌ **NO VERIFICADO** — ver nota |
| **BOLIVIA** | **10 años** para libros y documentos contables | Desde la fecha del último asiento contable | **Ley 393, art. 34.III** | ✅ (pero ver nota) |
| **UE (AML)** | **5 años**, con posibilidad de extensión nacional hasta 10 | Desde el fin de la relación o la transacción ocasional | Directiva (UE) 2015/849 (4AMLD), art. 40 | 🟡 |

**Notas de verificación:**

- ❌ **México — plazo NO confirmado.** El plazo de **10 años** es el consistentemente citado por la práctica profesional mexicana para los expedientes de identificación bajo el art. 115 LIC, pero **no pude confirmarlo en fuente primaria en esta sesión**: el DOF está bloqueado por `robots.txt`, y los tres documentos consultados (SIDOF 5644451, ABM, ordenjuridico.gob.mx) devolvieron fragmentos que no incluían la disposición de plazos. La referencia apunta a la **disposición 51ª** y a la **62ª Septies** (*"deberán conservar toda la documentación soporte"*, sin plazo en el fragmento). **Verificar la disposición 51ª completa del texto vigente antes de configurar la política de retención en México.**
- ⚠️ **Bolivia — el plazo de 10 años del art. 34.III de la Ley 393 se refiere a "libros y documentos referentes a sus operaciones"**, es decir, materia contable. El plazo específico del **expediente KYC** está en el **art. 66 del Instructivo UIF**, al que remite su art. 39(VII), y **ese artículo no fue recuperable** del PDF. ❌ **PENDIENTE.** El suelo aplicable en cualquier caso es el de 5 años del GAFI, siendo GAFILAT vinculante para Bolivia.

## C.11.2 La colisión: Art. 17 GDPR vs. obligación AML

**El conflicto no es real; es aparente.** El propio GDPR lo resuelve, pero la resolución debe implementarse correctamente.

**Art. 17.3(b) GDPR** exceptúa el derecho de supresión cuando el tratamiento sea necesario *"para el cumplimiento de una obligación legal que requiera el tratamiento de datos impuesta por el Derecho de la Unión o de los Estados miembros"*. La obligación de conservación AML es exactamente eso.

**Paraguay replica el mecanismo:** la Ley 7593/2025 prevé el derecho de supresión con respuesta en **30 días hábiles**, con **excepciones por obligación legal**.

**Sin embargo, la excepción no es un salvoconducto general.** Tres límites que definen la arquitectura correcta:

### 1. La excepción cubre lo *necesario*, no todo lo capturado

La obligación AML exige conservar el **expediente de identificación**: documento de identidad, datos del titular, evidencia de la verificación practicada. **No exige, en general, conservar la plantilla biométrica ni el vídeo completo de la sesión de liveness.**

> ⭐ **Consecuencia de diseño — la más importante de este apartado:** separar el ciclo de vida de los datos en **dos clases con políticas independientes**:
>
> | Clase | Contenido | Retención | Base |
> |---|---|---|---|
> | **Expediente KYC** (obligatorio) | Datos del documento, imágenes del documento, resultado de la verificación, evidencia de auditoría (timestamp, versión de modelo, umbrales aplicados, veredicto) | 5–10 años según país, desde el fin de la relación | Obligación legal AML → Art. 17.3(b) |
> | **Datos biométricos** (instrumentales) | Selfie, frames de liveness, vídeo de sesión, **plantilla biométrica** | **Mínima posible.** Borrado tras la verificación, salvo necesidad acreditada | Consentimiento / Art. 9.2 → **sujeto a supresión** |
>
> Esta separación permite responder afirmativamente a una solicitud de supresión de datos biométricos **sin incumplir la obligación AML**, porque lo que se conserva es el expediente, no el biométrico. Es la diferencia entre un "no podemos borrar nada" (indefendible ante una autoridad) y un "borramos su biometría y conservamos únicamente el expediente que la ley nos obliga a mantener" (defendible y correcto).
>
> ⚠️ **Excepción a considerar:** México. La CNBV permite a los bancos construir bases biométricas propias y la reforma de 2026 exige bitácoras de auditoría, lo que puede justificar una retención biométrica mayor **por parte del banco**. Pero eso es una decisión del responsable, no del middleware.

### 2. Bloqueo, no borrado — y no uso

La técnica correcta durante el período de retención obligatoria es el **bloqueo**: los datos se conservan, se restringe su tratamiento a la única finalidad de cumplir la obligación legal y atender requerimientos de autoridad, y se impide su uso comercial, analítico o de entrenamiento. La LFPDPPP mexicana ha usado tradicionalmente la figura de **bloqueo previo a la supresión**, y el GDPR ofrece el equivalente en la **limitación del tratamiento (Art. 18)**.

### 3. El reloj arranca al terminar la relación, no al captar el dato

Los plazos AML se computan **desde la finalización de la relación comercial**, no desde el onboarding. Esto exige que el middleware **no gestione la retención de forma autónoma**: sólo el cliente B2B sabe cuándo termina la relación con su cliente final. La arquitectura correcta expone al responsable un **evento/API de "fin de relación"** que dispara el cómputo, y una **política de purga configurable por tenant y por jurisdicción**. Una retención basada en "N años desde la captura" es incorrecta en todos los países analizados.

### C.11.3 Matriz operativa de retención

| Dato | Bolivia | Paraguay | México | UE |
|---|---|---|---|---|
| Expediente KYC (documento + datos + evidencia de verificación) | 10 años ⚠️/❌ | **5 años** ✅ | 10 años ❌ | 5 años (hasta 10) 🟡 |
| Plantilla biométrica | Minimizar | Minimizar (dato sensible) | Según instrucción del banco (base propia permitida) | Minimizar (Art. 9) |
| Vídeo de sesión / liveness | Minimizar | Minimizar | Registro *"íntegro y sin ediciones"* en no presencial 🟡 | Minimizar |
| Logs de auditoría (decisión, umbrales, versión de modelo) | Conservar con el expediente | Conservar con el expediente | Bitácoras exigidas por CNBV 🟡 | Conservar (accountability, Art. 5.2) |

> **Regla de oro:** la política de retención **debe fijarla el responsable** (cliente B2B) por escrito en el DPA, y el middleware **debe implementarla, no elegirla**. Como encargado, seleccionar unilateralmente el plazo de conservación es decidir sobre medios esenciales del tratamiento — con el riesgo de reclasificación a corresponsable del Art. 26 GDPR.

---

# D. SÍNTESIS: MATRIZ CONSOLIDADA

| Eje | Bolivia | Paraguay | México | UE |
|---|---|---|---|---|
| **Ley de datos personales** | ❌ **No existe** (sólo anteproyectos AGETIC / sociedad civil) | ✅ **Ley 7593/2025** — vacatio hasta ~nov 2027 | ✅ **LFPDPPP** (DOF 20/03/2025, vigente 21/03/2025) | ✅ GDPR 2016/679 |
| **Biometría = dato sensible** | s/d (anteproyecto: sí) | ✅ **Sí, expreso** | ⚠️ **No expreso** — vía interpretación | ✅ Sí, si identifica unívocamente (Art. 9) |
| **Autoridad de control** | ❌ No existe | 🆕 ANDP (MITIC) | 🔄 Secretaría Anticorrupción y Buen Gobierno (ex-INAI) | APD nacionales + EDPB |
| **Régimen del encargado** | ❌ No regulado | ✅ Sí (contrato, seguridad, auditorías) | ✅ Sí | ✅ Art. 28 (el más detallado) |
| **DPIA/EIPD obligatoria** | ❌ | ✅ Alto riesgo / automatizado | ❌ no verificado | ✅ Art. 35 |
| **Onboarding remoto regulado** | ❌ **Vacío** (vía: sandbox ASFI/ECP) | ❌ **Vacío** | ✅ **Sí** — arts. 51 Bis 6–9 + Anexo 71 | Vía eIDAS / EUDI |
| **Biometría exigida por el regulador financiero** | ❌ No | ❌ No | ✅ **Sí** (reforma 01/07/2026) | Sectorial |
| **Prohibición de delegar DDC** | ⚠️ **Sí — art. 32(II) Instructivo UIF** | No localizada | No localizada | No |
| **Retención KYC** | 10 años (contable) ⚠️ | **5 años** ✅ | 10 años ❌ | 5–10 años |
| **Adecuación GDPR** | No | No | No | — |
| **Hito de calendario** | Sandbox: adecuación desde 31/12/2025 | **Exigibilidad ~nov 2027** | **90 días hábiles** desde 02/07/2026 | **EUDI obligatorio sector privado: 06/12/2027** |

---

# E. INVENTARIO DE LO NO VERIFICADO

Puntos que **requieren verificación en fuente primaria** antes de comprometerse contractualmente. Se listan por prioridad de impacto:

| # | Elemento | Por qué importa | Dónde verificar |
|---|---|---|---|
| 1 | **Combinaciones de evidencia IAL2 en SP 800-63A-4** (rev-4, no rev-3) | Define el nivel de aseguramiento que el producto puede reclamar | `NIST.SP.800-63A-4.pdf`, sección IAL2 |
| 2 | **Umbral de coincidencia CNBV: ¿90 % o 98 %?** | Fuentes en conflicto; es un parámetro de configuración directo | DOF, resolución del 01/07/2026, Anexo 71 |
| 3 | **Plazo de retención KYC en México** | 10 años es lo citado, no confirmado en fuente primaria | Disposición 51ª de las DCG art. 115 LIC vigentes |
| 4 | **Art. 66 del Instructivo UIF Bolivia** (plazo de conservación) | El instructivo remite a él y no fue recuperable | Instructivo EIF R.A. N° 16 completo |
| 5 | **Interpretación del art. 32(II) UIF Bolivia** respecto de proveedores tecnológicos | Determina la viabilidad del modelo de negocio en Bolivia | Consulta formal a UIF/ASFI |
| 6 | **Fechas de transición 19794-5 → 39794-5** | Define el roadmap del lector de chip | ICAO Doc 9303 Parte 10, edición vigente |
| 7 | **Rango exacto del compuesto TD1** | Error de implementación de alto impacto | ICAO Doc 9303 Parte 5, tabla de layout MRZ |
| 8 | **¿ACER eliminado formalmente en 30107-3:2023?** | Afecta a cómo se reportan las métricas PAD | ISO/IEC 30107-3:2023, cláusula de métricas |
| 9 | **Fechas EUDI en fuente oficial** (no bufete) | Planificación del roadmap europeo | EUR-Lex, Reglamento (UE) 2024/1183, art. 5a |
| 10 | **¿Reglamento de la nueva LFPDPPP publicado?** | Zonas de incertidumbre operativa en México | DOF / Secretaría Anticorrupción |
| 11 | **Consentimiento expreso y por escrito para sensibles en la LFPDPPP 2025** | Diseño del flujo de consentimiento | Texto oficial de la ley (diputados.gob.mx) |
| 12 | **Resoluciones SEPRELAD/BCP posteriores a 2020 sobre identificación no presencial** | Podría existir habilitación no localizada | Índice de resoluciones vigentes del BCP |
| 13 | **Detalle de retención de registros y audit logs en SP 800-63A-4** | Configuración de la política de logs | `NIST.SP.800-63A-4.pdf`, sección de retención |
| 14 | **Valores FNMR de algoritmos líderes en FRTE 1:1** | Selección de proveedor de matcher | PDF del informe FRTE 1:1 de 08/05/2026 |
| 15 | **Estado normativo de ISO/IEC 30107-4** (ataques de inyección) | La CNBV ya los exige detectar | ISO/IEC JTC1 SC37 |

---

# F. CAMBIOS RECIENTES QUE ALTERAN EL DISEÑO (2025–2026)

| Fecha | Cambio | Impacto |
|---|---|---|
| **20 mar 2025** | 🔄 México: **nueva LFPDPPP**; extinción del INAI; autoridad → Secretaría Anticorrupción | Alto — cambia interlocutor regulatorio y criterios |
| **7 may 2025** | Bolivia: **DS 5384** regula las ETF (fintech) | Medio — abre vía de entrada |
| **3 jul 2025** | Bolivia: **Res. ASFI/540/2025** — Reglamento ETF + sandbox (ECP) | Medio — vía de entrada viable ante el vacío normativo |
| **1 ago 2025** | 🔄 **NIST SP 800-63-4 publicada como FINAL** (63A-4 el 01/08/2025) | **Alto** — KBA prohibida; umbrales FMR/FNMR/IAPAR ahora normativos y citables |
| **27–28 nov 2025** | 🔄 Paraguay: **Ley 7593/2025**, primera ley integral de datos; biometría = dato sensible | **Alto** — Paraguay pasa a estándar tipo GDPR |
| **8 may 2026** | NIST publica nuevo informe **FRTE 1:1** | Bajo — actualizar evidencia de proveedor |
| **1 jul 2026** | 🔄 México: **reforma CNBV** incorpora biometría facial a la CUB; prohíbe transferir bases biométricas; 90 días hábiles | **Alto** — obliga a rediseñar la titularidad de la base biométrica |
| **23 jul 2026** | 🔄 **ARF v3.0.0** del EUDI Wallet: *Functional Conformance Assessment Framework*, wallet-a-wallet, *Lists of Trusted Entities* | Alto — define el trabajo de integración europeo |
| **6 dic 2026** | ⏳ Estados miembros UE deben ofrecer wallet | Medio — inicio del ecosistema |
| **~nov 2027** | ⏳ Paraguay: exigibilidad plena de la Ley 7593 | Alto — ventana de adecuación |
| **6 dic 2027** | ⏳ **Sector privado regulado UE debe aceptar el EUDI Wallet** | **Crítico** — fecha límite del roadmap europeo |

---

## Conclusiones operativas

1. **Un único estándar técnico para las cuatro jurisdicciones es la estrategia correcta.** El techo lo marcan GDPR + SP 800-63A-4 IAL2 + CNBV México. Bolivia y Paraguay quedan cubiertos por defecto, y Paraguay lo exigirá formalmente desde ~nov-2027. Diferenciar por país multiplica el coste sin reducir riesgo.

2. **La regionalización del procesamiento (UE / LATAM) resuelve simultáneamente** el Capítulo V del GDPR (ningún país LATAM del alcance tiene adecuación), los TIA, y las expectativas de localización de los supervisores financieros.

3. **El posicionamiento contractual en Bolivia es una cuestión de viabilidad, no de redacción.** El art. 32(II) del Instructivo UIF prohíbe delegar la DDC: el producto debe ser herramienta, con la decisión de onboarding retenida por la entidad.

4. **La separación entre expediente KYC (retenible) y datos biométricos (minimizables)** es lo que hace compatibles la retención AML y el derecho de supresión. Es una decisión de arquitectura, no de política legal.

5. **Las dos fechas que estructuran el roadmap son el 6 de diciembre de 2027** (EUDI obligatorio para el sector privado regulado en la UE) **y ~noviembre de 2027** (exigibilidad de la Ley 7593 paraguaya). Coinciden en ventana: es un único ciclo de trabajo 2026–2027.

6. **La certificación PAD requiere matices en el discurso comercial:** iBeta Level 1/2 no acredita detección de ataques de inyección (ya exigida por la CNBV), no equivale a baja fricción (BPCER admitido: 15 %), y ACER no es métrica normativa de ISO/IEC 30107-3.

agentId: af84b961044b19eaa (use SendMessage with to: 'af84b961044b19eaa', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 156270
tool_uses: 102
duration_ms: 3291118</usage>