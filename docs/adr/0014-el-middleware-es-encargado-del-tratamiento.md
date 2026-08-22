# ADR-0014 — El middleware es encargado del tratamiento, y la decisión de onboarding la retiene la entidad cliente

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [11 — Cumplimiento normativo](../11-cumplimiento-normativo.md) · [12 — Retención y borrado](../12-retencion-y-borrado.md) · [ADR-0013](0013-residencia-de-datos-y-regionalizacion.md) · [ADR-0010](0010-revision-humana-construida-a-medida.md) · [ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md) |

## Contexto

La posición jurídica del producto respecto de los datos que trata **determina qué puede hacer el software y qué no**, y por tanto es una decisión de arquitectura.

Bajo el GDPR, el **art. 28** regula al encargado con obligaciones no negociables que se traducen en requisitos de producto: contrato vinculante con cada cliente; tratar los datos **únicamente siguiendo instrucciones documentadas** del responsable; confidencialidad del personal; medidas de seguridad del art. 32; **autorización previa para subencargados**; asistencia en derechos de los interesados y en brechas; supresión o devolución al terminar el servicio; y puesta a disposición de información para demostrar cumplimiento, incluidas auditorías.

Y una advertencia que condiciona el diseño más que ninguna otra: **un encargado que determina por su cuenta finalidades o medios esenciales pasa a ser corresponsable (art. 26)**, con responsabilidad directa. Entrenar modelos con datos de clientes sin instrucción es la vía más rápida a esa reclasificación.

Bolivia impone una restricción distinta y de mayor impacto comercial. El **art. 32(II) del Instructivo UIF vigente (EIF, R.A. N° 16, marzo de 2026)** establece: *«El Sujeto Obligado no podrá delegar a terceros la ejecución de las medidas de Debida Diligencia del cliente»*. De ahí tres consecuencias: el veredicto **debe tomarlo la entidad financiera**; debe existir un paso de decisión bajo su control, aunque esté automatizado con reglas que ella configura; y el lenguaje comercial debe evitar «realizamos su KYC» en ese mercado.

Paraguay refuerza la misma dirección: la Ley 7593/2025 obliga al encargado a incluir cláusulas de seguridad y notificación de incidentes y a **facilitar auditorías del responsable**.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Art. 28 GDPR: solo instrucciones documentadas | El middleware no fija por su cuenta umbrales ni finalidades |
| Art. 26 GDPR: riesgo de reclasificación | Determinar medios esenciales convierte al encargado en corresponsable |
| Art. 32(II) UIF Bolivia | La entidad no puede delegar la ejecución de la debida diligencia |
| Atractivo comercial de «nosotros decidimos» | Es la promesa más vendible y la que rompe la posición jurídica |
| Valor de un modelo mejorado con datos agregados | Prohibido sin instrucción o acuerdo expreso |
| Configurabilidad por cliente | Exige que umbrales y retención sean datos, no constantes |

## Opciones consideradas

### Opción A — Corresponsable, o responsable con finalidades propias

Finalidades propias declaradas: mejora de modelos, base antifraude compartida, analítica de sector.

**A favor**
- Habilita el activo de datos más valioso del sector: una base antifraude compartida detecta patrones que ningún cliente aislado ve.
- Permite mejorar los modelos con datos reales y diversos, con ventaja competitiva sostenible.
- Da libertad para fijar umbrales uniformes, simplificando el producto.

**En contra**
- **Responsabilidad directa** frente a interesados y autoridades, con exposición sancionadora propia sobre datos de categoría especial, y necesidad de DPIA y aparato de cumplimiento de responsable.
- Obliga a base de licitud propia por finalidad. Para biometría bajo el art. 9, difícil de sostener sin consentimiento explícito, que el middleware no recoge directamente.
- **Los clientes bancarios lo rechazan**: ningún departamento de cumplimiento acepta que su proveedor tenga finalidades propias sobre los datos biométricos de sus clientes.
- **Incompatible con el art. 32(II) boliviano**: un tercero que decide sobre la debida diligencia es lo que la norma prohíbe.

### Opción B — Encargado, con el veredicto emitido por el middleware

**A favor**
- Es la propuesta comercialmente más atractiva: el cliente integra una API y recibe una respuesta accionable.
- Reduce el trabajo de integración: el cliente no necesita su propio motor de decisión.
- Sigue siendo defendible bajo el GDPR si las reglas las fija el responsable.

**En contra**
- **Descalificador en Bolivia**: emitir el veredicto es ejecutar la medida de debida diligencia, que el art. 32(II) prohíbe delegar.
- Zona gris peligrosa: la frontera entre «ejecuto tus reglas» y «determino los medios esenciales» se cruza en cuanto el producto propone umbrales por defecto que los clientes aceptan sin revisar.
- Un rechazo automatizado con efectos jurídicos activa el art. 22 del GDPR, y quien debe responder es el responsable, que en ese diseño no participa.
- Concentra en el proveedor una responsabilidad que el cliente asume igualmente ante su supervisor, sin poder demostrar control.

### Opción C — Encargado estricto, con la decisión retenida por la entidad

El middleware ejecuta el tratamiento siguiendo instrucciones documentadas y entrega **señales y evidencias** —coincidencia biométrica con su puntuación, validez documental, resultado PAD, coincidencias en listas—, no un veredicto vinculante.

**A favor**
- **Compatible con el art. 32(II) boliviano**: el producto es herramienta con la que la entidad ejecuta por sí misma su debida diligencia.
- Encaja limpiamente en el art. 28 y elimina el riesgo de reclasificación como corresponsable.
- Es lo que el cumplimiento del cliente quiere oír: mantiene el control y puede demostrarlo ante su supervisor.
- Coherente con [ADR-0007](0007-registro-de-capacidades-dirigido-por-especificacion.md): si los umbrales son datos configurables, posición jurídica y arquitectura se refuerzan mutuamente.

**En contra**
- Comercialmente menos vistoso: hay que explicar por qué el producto «no decide».
- El cliente debe construir o configurar su capa de decisión, alargando la integración.
- Impide una base antifraude compartida sin acuerdo expreso de cada cliente, renunciando a un activo real.
- Obliga a que umbrales, plazos y políticas sean parámetros por tenant, con su complejidad de producto.

## Decisión

**Se adopta la opción C: el middleware actúa exclusivamente como encargado del tratamiento (art. 28 GDPR), y la decisión de onboarding la retiene la entidad cliente.**

El argumento decisivo es que **es la única posición viable en las cuatro jurisdicciones a la vez**: en la UE evita la reclasificación como corresponsable; en Bolivia es la única compatible con el art. 32(II); en Paraguay encaja con el régimen del encargado de la Ley 7593/2025; y en México es coherente con una reforma de la CNBV que prohíbe transferir bases biométricas.

Cinco reglas de producto, verificables en código y configuración:

1. **El responsable fija los umbrales; el middleware los implementa.** Ningún umbral es constante del código: todos son parámetros de la especificación del tenant. El producto puede **proponer** valores por defecto documentados; el responsable los acepta o los cambia, y esa aceptación queda registrada.
2. **El responsable fija los plazos de retención; el middleware los implementa.** La matriz varía por jurisdicción: **5 años** en Paraguay desde la finalización de la relación comercial (art. 42 de la Res. SEPRELAD 70/2019 y art. 18 de la Ley 1015/1997), **10 años** citado para Bolivia y México con verificación pendiente.
3. **El producto entrega señales y evidencias, no veredictos.** La API devuelve resultados con puntuación, umbral aplicado, proveedor, versión y evidencia; el paso de decisión queda bajo control de la entidad.
4. **Prohibición de finalidades propias.** No se reutilizan datos de un cliente para entrenar modelos, comparar ni construir bases antifraude compartidas **salvo instrucción o acuerdo expreso** ([ADR-0008](0008-ocr-generico-mas-llm-en-lugar-de-analyzeid.md)).
5. **Registro público de subencargados.** Un proveedor de cotejo facial, OCR, liveness o LLM **es subencargado** y debe declararse, con autorización previa y derecho de objeción.

El producto asume además tres obligaciones operativas del art. 28: endpoints de acceso, rectificación y supresión; **SLA de notificación de brecha compatible con las 72 horas del responsable**, en la práctica no superior a 24 horas; y procedimiento de terminación con certificado de borrado que incluya las copias de seguridad.

**El lenguaje comercial forma parte de la decisión**: la formulación correcta, en las cuatro jurisdicciones, es que el producto es la herramienta con la que la entidad ejecuta su debida diligencia.

## Consecuencias

### Positivas

- Una sola posición jurídica válida en las cuatro jurisdicciones, sin variantes contractuales por país.
- Elimina el riesgo de reclasificación como corresponsable y su exposición sancionadora directa.
- Facilita la venta a entidades reguladas: el cliente conserva el control y puede demostrarlo.
- El paquete de DPIA —tratamiento, flujos de datos, medidas técnicas, métricas APCER, BPCER, FMR y FNMR, sesgo demográfico, subencargados y ubicaciones— es obligación y diferenciador a la vez.

### Negativas

- Se renuncia a la base antifraude compartida y a entrenar modelos con datos de clientes, lo que además cierra la opción de un modelo propio de extracción.
- La integración del cliente es más larga: debe configurar umbrales y disponer de su capa de decisión.
- El discurso comercial es más difícil frente a competidores que prometen decidir.
- Cada umbral y plazo configurable añade superficie de configuración, validación y pruebas.

### Neutras

- La consola de revisión humana admite revisores de la entidad, de modo que la decisión final queda atribuida a ella ([ADR-0010](0010-revision-humana-construida-a-medida.md)).
- La plantilla de contrato de tratamiento es estándar y no opcional: objeto, duración, naturaleza, finalidad, tipo de datos y categorías de interesados.
- El derecho de auditoría puede sustituirse por informes de tercero (SOC 2, ISO 27001) cuando así se pacte.

## Criterios de revisión

- **Si la ASFI o la UIF de Bolivia emiten criterio interpretativo** que module el art. 32(II) respecto de proveedores tecnológicos —hoy **no verificado**, y la consulta prioritaria antes de entrar en ese mercado—, procede reevaluar hasta dónde puede llegar la automatización.
- **Si un cliente solicita expresamente y por escrito** participar en una base antifraude compartida, esa finalidad puede habilitarse para él, con análisis de si constituye corresponsabilidad.
- **Si la reforma de la CNBV fija requisitos de titularidad de la base biométrica** incompatibles con el diseño, hay que revisar dónde reside y quién la controla.
- **Si se verifica el plazo de conservación del expediente KYC en Bolivia** —el art. 39(VII) remite al art. 66, no recuperable—, hay que sustituir el valor provisional de 10 años.
- **Si el producto determina de facto un medio esencial**, hay que corregirlo como defecto de cumplimiento, no aceptarlo como característica.

## Referencias

- [cumplimiento-normativo-y-estandares §B.6.2 — art. 28 GDPR](../referencias/cumplimiento-normativo-y-estandares.md)
- [cumplimiento-normativo-y-estandares §B.8.2 — art. 32(II) del Instructivo UIF de Bolivia](../referencias/cumplimiento-normativo-y-estandares.md)
- [cumplimiento-normativo-y-estandares §B.9 — Ley 7593/2025 y Res. SEPRELAD 70/2019](../referencias/cumplimiento-normativo-y-estandares.md)
- [Reglamento (UE) 2016/679, arts. 26, 28, 32 y 35 — EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [UIF Bolivia — Instructivo EIF R.A. N° 16 (2026)](https://www.uif.gob.bo/wp-content/uploads/2026/03/INSTRUCTIVO-EIF-R.A.-No.-16-1.pdf)
- [Resolución SEPRELAD N° 70/2019](https://baselegal.com.py/docs/8c9cc0ef-eac1-11e9-aeeb-525400c761ca/text)
- [SEPRELAD — Ley 1015/1997 actualizada, art. 18](https://www.seprelad.gov.py/resoluciones/resoluciones/ley10151997actualizada_.pdf)
