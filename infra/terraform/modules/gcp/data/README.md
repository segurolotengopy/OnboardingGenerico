# Modulo `gcp/data`

## Que crea

- **Base de datos Firestore compartida** (modo Native) con concurrencia optimista, PITR y proteccion de
  borrado parametrizables, y CMEK explicita.
- **Una base de datos dedicada por tenant premium**, con binding de IAM condicionado al recurso
  `database`. Es el unico aislamiento **real** de plano de datos disponible en GCP.
- **Politicas de TTL** sobre `expires_at` (coleccion efimera) y `lock_expires_at` (mutex).
- **Indices compuestos** para casos por estado, cola de revision y Registro de Capacidades.

## Advertencias

### 🔴 No existe `dynamodb:LeadingKeys` — y esto es donde se nota

Las condiciones de IAM de GCP **no exponen ningun atributo de clave de fila ni de identificador de
documento**. El binding condicionado de este modulo acota el acceso al **recurso base de datos**, no a
documentos dentro de ella. Es lo maximo que permite la plataforma.

Y **las Security Rules de Firestore no ayudan**: las bibliotecas de cliente de servidor las omiten por
completo. Solo protegen SDK de cliente movil o web.

**Como se compensa:**

1. **Cifrado de sobre por tenant con `tenant_id` como Associated Data** (modulo `gcp/kms`). Es el
   control **primario**: un error de alcance produce un fallo de descifrado, no una fuga.
2. **Base de datos dedicada por tenant premium** (este modulo). Tope de **100 bases de datos por
   proyecto**: no escala a miles de tenants.
3. **VPC Service Controls** como perimetro (comentado en `gcp/identity`, requiere Organizacion).
4. **Data Access audit logs** con alerta de desalineacion entre el tenant del path y el del token
   (habilitados en `gcp/identity`). Detectan; no previenen.
5. En el codigo: **un unico repositorio con alcance de tenant** y pruebas de arquitectura que fallen si
   el cliente de Firestore se importa fuera del adaptador.

### Modelado

- **El patron single-table no se emula bien en Firestore.** El mapeo mas fiel es una coleccion plana
  con identificadores de documento compuestos (`TENANT#<t>#CASE#<c>`) y consultas de rango sobre
  `__name__`, que reproduce `begins_with` porque los identificadores se ordenan lexicograficamente.
- **Si el modelo real es agresivamente single-table, el destino correcto es Bigtable o Spanner**, no
  Firestore. Spanner es ademas el unico de GCP con change streams reales (orden garantizado y
  reproduccion de hasta 7 dias). Elegir Firestore por reflejo "NoSQL a NoSQL" y descubrir despues que
  no hay consultas de rango sobre sort key es un fallo caro.
- **El puerto de repositorio debe exponer operaciones de dominio**, nunca `query(PK, SK begins_with)`.
  Si el puerto ya acepta primitivas de DynamoDB, ese es el primer refactor.

### Limites y trampas

- **El TTL de Firestore no borra subcolecciones.** Expirar un caso modelado como
  `/casos/{c}/documentos/{d}` deja las subcolecciones huerfanas. Por eso el modelo es de colecciones
  planas.
- **El borrado por TTL ocurre "tipicamente dentro de 24 horas"** tras la expiracion, no es garantizado
  ni transaccional, y **los documentos expirados siguen apareciendo en consultas** hasta que se borran
  de verdad. No sirve como mecanismo de supresion para cumplimiento.
- **Un solo campo TTL por grupo de colecciones**; maximo 1.000 configuraciones a nivel de campo.
- **Documento: 1 MiB.** Mas generoso que los 400 KB de DynamoDB, pero cuidado con el limite de **40.000
  entradas de indice por documento**: un documento con mapas anidados grandes lo revienta antes que el
  de tamano. Desactive la indexacion de los campos que no consulta.
- **Firestore + Eventarc no es DynamoDB Streams.** No hay garantia de orden estricto ni reproduccion
  del stream. Si la saga depende del orden por caso, necesita numero de secuencia explicito en el
  documento y reordenacion en el consumidor, o Pub/Sub con claves de ordenacion. Disene los consumidores
  como idempotentes y reentrantes desde el principio.
- **`location_id` es inmutable.** Cambiarlo exige crear una base de datos nueva y migrar.
- **La base de datos `(default)` no puede eliminarse.** Si quiere poder destruir el entorno por
  completo, use un nombre propio en `shared_database_name`.
- **Cloud KMS Autokey no soporta Firestore.** La CMEK debe declararse de forma explicita. Y recuerde:
  CMEK es cifrado en reposo a nivel de servicio, **no** cifrado de campo. Si el requisito es que el
  operador de la plataforma no pueda leer datos de un tenant, hace falta cifrado de aplicacion.
- Transaccion: **270 segundos** (60 segundos de inactividad); peticion a la API: **10 MiB**.
