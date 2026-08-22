# ADR-0009 — Liveness mediante un único proveedor SaaS con certificación iBeta PAD para ambas nubes

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [09 — Biometría y liveness](../09-biometria-y-liveness.md) · [15 — Catálogo de proveedores y licencias](../15-catalogo-de-proveedores-y-licencias.md) · [ADR-0001](0001-arquitectura-hexagonal-multinube.md) · [ADR-0012](0012-politica-de-licencias-de-terceros.md) · [11 — Cumplimiento normativo](../11-cumplimiento-normativo.md) |

## Contexto

La detección de vida —*Presentation Attack Detection*— impide que una fotografía, un vídeo reproducido en pantalla o una máscara pasen por una persona presente. En un onboarding remoto es donde se concentra el fraude.

Los hechos que condicionan la decisión:

- **En GCP no existe liveness gestionado.** Cloud Vision declara explícitamente que no soporta reconocimiento facial individual: sin antispoofing, sin reto de vivacidad, sin SDK de cliente. Es la brecha 1 de la matriz de paridad.
- **En AWS sí existe**, pero incluye **SDK de captura en el cliente**. `LivenessPort` no es un puerto puramente de servidor: cambiar de adaptador implica trabajo de aplicación móvil o web.
- **La CNBV mexicana exige prueba de vida certificada desde el 1 de julio de 2026**, con capacidad de detectar *deepfakes*, máscaras, fotos estáticas y **ataques de inyección**, con 90 días hábiles de adecuación desde el 2 de julio de 2026.
- **NIST SP 800-63A-4, final desde el 1 de agosto de 2025**, exige PAD en recolección biométrica remota con **IAPAR < 0,07** conforme a **ISO/IEC 30107-3:2023**.
- **ASFI y BCP/SEPRELAD no fijan umbral PAD alguno**: el techo lo marcan la CNBV y el GDPR.

Sobre las alternativas abiertas, el catálogo de licencias es concluyente: el único componente de antispoofing facial con licencia limpia es `minivision-ai/Silent-Face-Anti-Spoofing` (Apache-2.0), pero es un **modelo de 2020**. Además, varios pesos del ecosistema facial —InsightFace `buffalo_l` entre ellos— arrastran restricciones de uso no comercial **independientes de la licencia del código** ([ADR-0012](0012-politica-de-licencias-de-terceros.md)).

Y una advertencia que suele omitirse: **los ataques de inyección no son ataques de presentación**. Una cámara virtual, un *hooking* del stream o un *deepfake* insertado en el pipeline quedan **fuera del alcance de ISO/IEC 30107-3**. Una certificación iBeta PAD, por alto que sea su nivel, **no acredita** protección frente a ellos.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| CNBV exige prueba de vida certificada y detección de inyección | El control es obligatorio y la certificación exigible |
| GCP no ofrece liveness gestionado | Un adaptador por nube produciría asimetría de garantías |
| El SDK de captura vive en el cliente | Cambiar de proveedor cuesta trabajo de aplicación |
| Modelos abiertos de 2020 y pesos restringidos | Construir propio es inviable legal y técnicamente |
| Dependencia de un proveedor único | Riesgo de continuidad y de poder de negociación |
| La certificación PAD no cubre inyección | Hace falta un control adicional al margen de la certificación |

## Opciones consideradas

### Opción A — Liveness propio con modelos abiertos

**A favor**
- Sin coste por transacción ni dependencia de un tercero en el camino crítico.
- Control total sobre modelo, umbrales y evolución.
- Portable por construcción: el mismo componente en las dos nubes, sin brecha.
- Sin enviar biometría a un subencargado adicional, lo que simplifica el registro del DPA.

**En contra**
- **Descalificador regulatorio: no es certificable.** La CNBV exige prueba de vida certificada, y la investigación recomienda explícitamente **no construir liveness propio con modelos abiertos para KYC en producción**.
- El modelo con licencia limpia es de **2020**; el estado del arte del ataque ha avanzado mucho más.
- Someterlo a evaluación iBeta implicaría repetir la certificación con cada cambio del modelo: es otro negocio.
- Los pesos de calidad arrastran con frecuencia restricciones no comerciales.
- Traslada al equipo la carga de defender ante un supervisor las métricas APCER, BPCER y RIAPAR.

### Opción B — Servicio gestionado de cada nube, con adaptador por nube

**A favor**
- En AWS, integración nativa, facturación unificada y latencia mínima.
- Sin contrato adicional ni subencargado nuevo en el despliegue de AWS.
- Ruta de menor fricción para el primer cliente si despliega en AWS.

**En contra**
- **Descalificador: no hay nada que usar en GCP.** La brecha no es de calidad, es de existencia.
- Produce la peor forma de asimetría: garantías biométricas distintas según la nube del cliente, que hay que explicar en cada DPIA.
- Como el SDK vive en el cliente, dos proveedores significan **dos integraciones de frontend** y dos conjuntos de métricas que calibrar.
- La investigación observa que `LivenessPort` acabaría con **tres** adaptadores —AWS, SaaS para GCP y potencialmente el mismo SaaS en AWS—, señal de que la asimetría se gestiona en lugar de eliminarse.

### Opción C — Un único proveedor SaaS certificado, en ambas nubes

**A favor**
- **Elimina la asimetría de raíz**: una integración de frontend, un conjunto de métricas, un comportamiento.
- La certificación es del proveedor y es exhibible ante la CNBV y ante el área de cumplimiento del cliente; el middleware no defiende métricas PAD propias.
- El proveedor mantiene el modelo frente a la evolución del ataque, que es una carrera continua de dedicación completa.
- `LivenessPort` pasa de riesgo alto a riesgo bajo en el portaje.
- Permite exigir contractualmente detección de ataques de inyección, que ninguna certificación PAD cubre.

**En contra**
- Dependencia de un proveedor único en un control obligatorio: si cae, el onboarding se detiene.
- Coste por transacción y poder de negociación limitado una vez integrado el SDK.
- El proveedor es **subencargado** y debe declararse, con su evaluación de transferencias internacionales ([ADR-0013](0013-residencia-de-datos-y-regionalizacion.md)).
- El SDK integrado en la aplicación del cliente hace costoso cambiar de proveedor aunque el puerto esté bien diseñado.
- La certificación tiene matices que comunicar con honestidad: el **BPCER admitido por iBeta es del 15 %**, muy laxo frente a lo que tolera un onboarding comercial.

## Decisión

**Se adopta la opción C: un único proveedor SaaS con certificación iBeta PAD vigente, como implementación de `LivenessPort` en ambas nubes.**

El argumento decisivo es regulatorio antes que técnico: la CNBV exige prueba de vida **certificada**, y eso solo lo aporta un tercero evaluado por laboratorio acreditado. Dado que hay que contratar a un tercero de todos modos para GCP, usar el mismo en AWS **convierte una brecha de paridad en una no-brecha**, al coste de renunciar a un gestionado que además obligaría a una segunda integración de frontend.

Tres requisitos explícitos que no se derivan de la certificación:

1. **Detección de ataques de inyección como requisito contractual separado.** ISO/IEC 30107-3 cubre ataques de **presentación**; la cámara virtual, el *hooking* y el *deepfake* inyectado quedan fuera. La CNBV ya los exige. El proveedor debe acreditar atestación de dispositivo y de aplicación, integridad del canal de captura y detección de cámara virtual, evaluados al margen de la certificación PAD. El estado normativo de ISO/IEC 30107-4 **no está verificado** y no puede darse por hecho.
2. **Métricas conforme a la norma, no de marketing.** Se exige APCER y BPCER **por separado** y RIAPAR, obligatoria desde la edición de 2023. **No se acepta un ACER como evidencia de conformidad**: promediar oculta el peor caso, y ACER no es métrica normativa de reporte. El objetivo operativo es **BPCER entre 2 % y 5 % con APCER próximo a 0** en las especies de nivel 1 y 2 —muy por debajo del 15 % que admite iBeta—, y ese ajuste es decisión de diseño del middleware.
3. **Umbral normativo trazable**: donde aplique NIST SP 800-63A-4, **IAPAR < 0,07** conforme a ISO/IEC 30107-3:2023.

El riesgo de proveedor único se mitiga manteniendo `LivenessPort` estricto —`create_session`, `get_result`— y con una ficha de evaluación estandarizada que permita cualificar un segundo proveedor sin rediseñar el puerto. Se acepta que el cambio real seguiría costando trabajo de frontend.

`FaceMatchPort` permanece **separado**: unirlos en un `BiometricsPort` arrastraría el problema de portabilidad del segundo al primero, que se porta sin fricción.

## Consecuencias

### Positivas

- Garantía biométrica idéntica en las dos nubes, con un solo conjunto de métricas que calibrar y comunicar.
- Certificación exhibible ante la CNBV y ante el cumplimiento del cliente, aportada por un tercero.
- Una sola integración de SDK de captura en las aplicaciones cliente.
- `LivenessPort` deja de ser un puerto de riesgo alto en el portaje.
- El requisito de detección de inyección queda explícito en el contrato, no diluido en la certificación.

### Negativas

- Dependencia de un proveedor único en un control obligatorio, con riesgo de continuidad de negocio.
- Coste por transacción que escala con el volumen y poder de negociación limitado tras la integración.
- Subencargado adicional que declarar y evaluar.
- El SDK en la aplicación del cliente convierte el cambio de proveedor en un proyecto conjunto con cada requirente.
- Se renuncia a un servicio gestionado disponible en la nube de referencia.

### Neutras

- La ficha de evaluación fija los criterios de cualificación de una alternativa: certificación vigente, métricas por especie, controles de inyección, cobertura demográfica y disponibilidad regional.
- El resultado PAD se registra como evidencia con proveedor, versión, umbral y métricas.

## Criterios de revisión

- **Si GCP publica liveness gestionado con certificación conforme a ISO/IEC 30107-3**, procede reevaluar la vuelta a servicios gestionados por nube.
- **Si la certificación del proveedor caduca o no se renueva** conforme a la edición vigente, deja de ser apto de inmediato y se activa la cualificación del alternativo.
- **Si ISO/IEC 30107-4 alcanza estado normativo** con esquema de certificación, el requisito contractual pasa a ser certificación exigible.
- **Si el BPCER medido en producción supera el 5 %** de forma sostenida, hay que recalibrar o cambiar de proveedor aunque la certificación siga vigente.
- **Si un ataque de inyección confirmado atraviesa el control**, se reevalúa el proveedor completo, no solo el umbral.

## Referencias

- [gcp-paridad-de-servicios §3, brecha 1 — liveness facial gestionado](../referencias/gcp-paridad-de-servicios.md)
- [cumplimiento-normativo-y-estandares §A.2 — ISO/IEC 30107-3, niveles iBeta y umbrales por regulador](../referencias/cumplimiento-normativo-y-estandares.md)
- [cumplimiento-normativo-y-estandares §B.7.4 — reforma CNBV del 1 de julio de 2026](../referencias/cumplimiento-normativo-y-estandares.md)
- [iBeta — ISO 30107-3 PAD Test Methodology and Confirmation Letters](https://www.ibeta.com/iso-30107-3-presentation-attack-detection-confirmation-letters/)
- [ISO/IEC 30107-3:2023 — IEC Webstore](https://webstore.iec.ch/en/publication/81714)
- [NIST SP 800-63A-4](https://pages.nist.gov/800-63-4/sp800-63a.html)
- [minivision-ai/Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing)
