# ADR-0013 — Residencia de datos por regionalización: instancias independientes para la UE y para LATAM

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-08-21 |
| Decisores | Arquitectura de plataforma |
| Documentos relacionados | [11 — Cumplimiento normativo](../11-cumplimiento-normativo.md) · [ADR-0014](0014-el-middleware-es-encargado-del-tratamiento.md) · [12 — Retención y borrado](../12-retencion-y-borrado.md) · [ADR-0005](0005-aislamiento-multitenant-en-capas.md) · [16](../16-guia-de-despliegue-aws.md) · [17](../17-guia-de-despliegue-gcp.md) |

## Contexto

El producto opera en **Bolivia, Paraguay, México y la Unión Europea**, y trata datos biométricos que el GDPR clasifica como categoría especial (art. 9) y que la Ley 7593/2025 paraguaya declara expresamente dato sensible.

El hecho que estructura la decisión es verificado: **ninguno de los tres países LATAM del alcance tiene decisión de adecuación de la Comisión Europea.** Ni México, ni Bolivia, ni Paraguay.

Las consecuencias del **Capítulo V del GDPR** son directas:

1. Toda transferencia UE → BO/PY/MX requiere **garantías adecuadas**: en la práctica, **Cláusulas Contractuales Tipo** conforme a la Decisión de Ejecución (UE) 2021/914, en el módulo responsable→encargado o encargado→subencargado.
2. Se necesita un **Transfer Impact Assessment** por destino, evaluando el marco de acceso gubernamental a los datos. Para biometría de categoría especial, ese análisis es exigente y sostenerlo en el tiempo es costoso.
3. **El acceso remoto desde LATAM a datos alojados en la UE es una transferencia internacional**, aunque los datos no se muevan: un ingeniero de soporte en Ciudad de México que abre una consola sobre un expediente europeo está transfiriendo.

Hay presión concurrente desde el otro lado: los supervisores financieros latinoamericanos tienden a imponer expectativas de localización, y la reforma de la CNBV del 1 de julio de 2026 **prohíbe transferir bases biométricas**.

La conclusión operativa de la investigación normativa es explícita: la regionalización resuelve simultáneamente el Capítulo V, los TIA y las expectativas de localización, y **su coste es sensiblemente menor que el de sostener SCC y TIA para datos biométricos de categoría especial**.

## Fuerzas en tensión

| Fuerza | Implicación |
|---|---|
| Ningún país LATAM del alcance tiene adecuación | Todo flujo UE→LATAM exige SCC más TIA por destino |
| Datos de categoría especial | El listón probatorio del TIA es más alto |
| El acceso remoto de soporte es transferencia | No basta regionalizar datos: hay que regionalizar la operación |
| Coste de operar varias instancias | Duplica despliegue, observabilidad, guardias y pruebas |
| Expectativas de localización de supervisores | Empujan en la misma dirección que el Capítulo V |
| Clientes que operan en ambas regiones | Necesitan una vista consolidada que la regionalización dificulta |

## Opciones consideradas

### Opción A — Instancia global única con SCC y TIA

Un despliegue central —típicamente en la UE, por ser el marco más exigente— para todos los clientes.

**A favor**
- Una sola instancia que operar, observar y actualizar: el modelo más barato en infraestructura y en esfuerzo de ingeniería.
- Vista consolidada natural para clientes multinacionales y para la operación interna.
- Un solo entorno donde razonar sobre versiones, especificaciones y datos.

**En contra**
- **Requiere SCC más TIA por cada destino LATAM**, sobre datos de categoría especial, y mantenerlos vigentes ante cambios normativos. El coste jurídico recurrente supera al de la infraestructura duplicada.
- El acceso de soporte desde LATAM a datos europeos es transferencia y hay que cubrirlo específicamente.
- **Choca con la prohibición de la CNBV de transferir bases biométricas**: mantener la base biométrica de clientes mexicanos en la UE es lo que la reforma pretende impedir.
- Latencia elevada para usuarios latinoamericanos en un flujo con captura de vídeo.
- Es la arquitectura más difícil de defender: «¿por qué los datos de este ciudadano boliviano viajan a Irlanda?» no tiene buena respuesta.

### Opción B — Instancia por país

**A favor**
- Satisface cualquier expectativa de localización, presente o futura, sin discusión.
- El borrado por jurisdicción es trivial: se destruye el despliegue.
- Aísla el impacto de un incidente o de un cambio normativo a un solo país.

**En contra**
- Coste operativo desproporcionado para el volumen esperado de Bolivia y Paraguay, que son mercados de entrada.
- **Ninguna de las dos nubes ofrece regiones en Bolivia ni en Paraguay**: «instancia por país» sería en realidad una instancia en una región latinoamericana etiquetada por país, pagando el coste sin obtener la localización real.
- Multiplica por cuatro guardias, despliegues, pruebas de paridad y superficie de configuración.
- Dificulta operar el producto con un equipo pequeño y aumenta la probabilidad de divergencia.

### Opción C — Regionalización en dos instancias: UE y LATAM

Dos instancias independientes, cada una con su plano de datos, sus claves, su almacenamiento de evidencia y su operación.

**A favor**
- **Elimina la mayor parte del problema del Capítulo V**: si no hay transferencia, no hay que justificarla. Los SCC quedan reservados a subencargados concretos.
- Simplifica el TIA: en lugar de evaluar tres países para el flujo principal, se evalúa solo para subencargados específicos.
- Satisface las expectativas de localización de los supervisores financieros con el mismo mecanismo.
- Latencia adecuada para cada mercado en un flujo con captura de vídeo.
- Coste de dos instancias, no de cuatro, con la misma base de código y los mismos módulos de infraestructura.
- Encaja con la arquitectura ya adoptada: la instancia es una dimensión de despliegue, no de diseño.

**En contra**
- Duplica despliegue, observabilidad, guardias y pruebas de regresión: cada cambio se valida dos veces.
- Un cliente multinacional necesita dos contratos y no obtiene vista consolidada sin agregación explícita.
- **La regionalización de datos no basta**: hay que regionalizar la operación, porque el acceso de soporte transfronterizo es transferencia.
- No resuelve por sí sola la prohibición de la CNBV: México está dentro de la instancia LATAM y hay que verificar que la titularidad y ubicación de la base biométrica cumplen la reforma.

## Decisión

**Se adoptan dos instancias regionales independientes —Unión Europea y LATAM— con separación completa de plano de datos, material criptográfico y almacenamiento de evidencia.**

El argumento decisivo es de coste comparado: **mantener SCC y TIA vigentes para datos biométricos de categoría especial hacia tres destinos sin adecuación cuesta más —en dinero, en asesoría y en riesgo residual— que operar una segunda instancia.** La regionalización no es un lujo de cumplimiento: es la opción barata. El de refuerzo es que resuelve **tres problemas con un mecanismo**: Capítulo V, expectativas de localización y latencia.

Cuatro reglas:

1. **Ningún dato personal cruza la frontera entre instancias**: ni expedientes, ni artefactos, ni eventos de auditoría, ni copias de seguridad. Las especificaciones de flujo y el registro de capacidades, que no contienen datos personales, sí se replican.
2. **El material criptográfico es regional.** Cada instancia tiene su jerarquía de claves y sus claves por tenant ([ADR-0005](0005-aislamiento-multitenant-en-capas.md)): una clave de una región no puede descifrar datos de la otra, lo que convierte la separación en control técnico y no solo en política.
3. **La operación se regionaliza junto con los datos.** El acceso de soporte transfronterizo se restringe por diseño y, donde sea inevitable, se cubre contractualmente y se registra en la cadena de auditoría.
4. **Los subencargados se evalúan por región.** El proveedor de liveness ([ADR-0009](0009-liveness-mediante-proveedor-certificado-unico.md)), el de cribado AML y el de LLM deben ofrecer procesamiento dentro de la región. Donde no sea posible, ese flujo requiere SCC y TIA propios, declarados en el registro de subencargados.

La asignación de un tenant a una instancia la determina **la residencia de los titulares que trata**, no el domicilio del cliente.

Queda fuera del alcance de este ADR, y remitido a verificación, si la reforma de la CNBV exige además que la base biométrica de clientes mexicanos resida bajo titularidad de la entidad y en territorio mexicano. <!-- PENDIENTE DE VERIFICAR -->

## Consecuencias

### Positivas

- El flujo principal deja de ser transferencia internacional: desaparece la necesidad de SCC y TIA para el grueso del tratamiento.
- Argumentación sencilla ante una autoridad de control: los datos del titular no salen de su región.
- Latencia adecuada en cada mercado para un flujo con captura de vídeo.
- La separación criptográfica hace que un error de enrutamiento produzca fallo de descifrado, no fuga transfronteriza.
- Se satisfacen simultáneamente las expectativas de localización de los supervisores financieros.

### Negativas

- Dos instancias que desplegar, observar, parchear y guardar, con su coste de personal e infraestructura.
- Un cliente multinacional necesita dos relaciones de servicio y no obtiene vista consolidada sin agregación construida a propósito.
- El soporte debe regionalizarse o cubrirse contractualmente, lo que restringe el modelo de guardias.
- Riesgo de divergencia de configuración, controlable con los mismos módulos de infraestructura y pruebas de paridad.
- Los subencargados sin procesamiento regional obligan a mantener SCC y TIA acotados: el problema se reduce, no desaparece.

### Neutras

- La instancia regional es una dimensión de despliegue: sin ramas de código por región, solo variables de entorno y módulos parametrizados.
- La retención y el borrado siguen la matriz por jurisdicción de [12](../12-retencion-y-borrado.md), que ya es regional por naturaleza.

## Criterios de revisión

- **Si la Comisión Europea adopta una decisión de adecuación** para México, Paraguay o Bolivia, el fundamento principal se debilita para ese país y procede reevaluar la consolidación.
- **Si la Ley 7593/2025 paraguaya, al alcanzar exigibilidad plena hacia noviembre de 2027**, impone requisitos de localización propios, hay que verificar que la instancia LATAM los satisface.
- **Si un supervisor exige localización nacional efectiva** y la nube no ofrece región en ese país, hay que reevaluar la opción B para ese mercado o renunciar a él.
- **Si el coste operativo de la segunda instancia supera el de mantener SCC y TIA** —comparación que debe rehacerse anualmente con cifras reales—, la premisa económica deja de sostenerse.
- **Si aparece un cuarto mercado fuera de las dos regiones**, el criterio para adherirlo o abrir una tercera instancia es el mismo: coste de la instancia frente a coste de las garantías de transferencia.

## Referencias

- [cumplimiento-normativo-y-estandares §B.6.6 — transferencias internacionales, Capítulo V](../referencias/cumplimiento-normativo-y-estandares.md)
- [cumplimiento-normativo-y-estandares §D — matriz consolidada](../referencias/cumplimiento-normativo-y-estandares.md)
- [cumplimiento-normativo-y-estandares §F y conclusiones operativas, punto 2](../referencias/cumplimiento-normativo-y-estandares.md)
- [Reglamento (UE) 2016/679 (GDPR) — EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [Decisión de Ejecución (UE) 2021/914 — Cláusulas Contractuales Tipo](https://eur-lex.europa.eu/eli/dec_impl/2021/914/oj)
- [Ley N° 7593/2025 de Paraguay — BACN](https://www.bacn.gov.py/leyes-paraguayas/12924/ley-n-7593-2025-de-protecci-n-de-datos-personales-en-la-rep-blica-del-paraguay)
