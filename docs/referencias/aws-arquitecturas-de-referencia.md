# Síntesis técnica de 6 fuentes de arquitectura AWS
### Base de diseño para middleware serverless multi-tenant de onboarding/eKYC

---

## Ficha 1 — Patrones de aislamiento multi-tenant, ABAC y STS session tags

**URL:** https://hidekazu-konishi.com/entry/aws_saas_multi_tenant_architecture_guide.html
**Recuperación:** ✅ Exitosa (contenido completo, con fragmentos de código y políticas IAM)

### Resumen técnico

La guía estructura el aislamiento multi-tenant como una decisión **por recurso**, no por aplicación completa. Define tres modelos: **Silo** ("each tenant gets dedicated resources", frontera física — tablas o cuentas dedicadas; aislamiento máximo, sobrecarga operativa alta), **Pool** ("tenants share the same resources, and isolation is enforced logically at the row/item level"; eficiencia máxima pero dependiente de que la aplicación de controles sea correcta), y **Bridge** ("a mixture. Some resources are siloed, others pooled"), que habilita estrategias por tier — tenants premium con capacidad dedicada, tiers básicos compartiendo infraestructura.

El eje central del documento es que **el aislamiento debe ser impuesto por la plataforma (IAM/STS), no por lógica de aplicación**: "IAM/STS enforce boundaries that application bugs cannot bypass". El flujo de identidad de tenant arranca en Cognito con un **pre token generation Lambda trigger (evento V2.0)** que inyecta el claim `https://aws.amazon.com/tags` con `principal_tags`, más un claim `tenant_id` en el access token. Requisito crítico declarado: **el trigger falla cerrado** — "if a user has no tenant assignment, no token is issued".

Ese claim se convierte en **session tags** vía `AssumeRoleWithWebIdentity`. La trust policy del rol debe permitir explícitamente **ambas** acciones `sts:AssumeRoleWithWebIdentity` y `sts:TagSession`, con condición sobre el `aud` del pool de Cognito. Las credenciales resultantes llevan `aws:PrincipalTag/TenantID`, que se consume en las políticas de permisos.

Para DynamoDB, el patrón es **fine-grained access control con `dynamodb:LeadingKeys`**, con dos advertencias operativas que la fuente subraya: la clave de condición es plural incluso para acciones de ítem único, y **debe usarse el modificador de conjunto `ForAllValues:`**. El esquema recomendado usa `pk = TENANT#<tenantId>` y `sk = ORDER#<orderId>` / `USER#<userId>`. Advertencia sobre índices: `LeadingKeys` restringe la partition key de la tabla base; un **LSI** comparte esa PK y queda protegido, pero un **GSI no** — hay que mantener el tenant ID como PK del GSI o excluir GSIs no indexados por tenant.

Para KMS el aislamiento se logra con **grants por tenant** restringidos con `EncryptionContextEquals={tenant=<tenantId>}`. Para S3 se usa scoping por prefijo con `${aws:PrincipalTag/TenantID}` en el Resource, más una sentencia separada para `s3:ListBucket` condicionada por `s3:prefix`. La medición por tenant se emite con **CloudWatch EMF** (sin llamadas API síncronas), añadiendo la dimensión `TenantId`.

Principios declarados: fail-closed por defecto; nunca confiar en input del cliente para la identidad de tenant; verificación continua ("a boundary you have not tried to break is a boundary you do not know works"); y tenancy observable en todos los logs, métricas y trazas de auditoría.

### Fragmentos reutilizables (transcritos)

**Pre token generation trigger (Cognito, V2.0):**
```python
event["response"]["claimsAndScopeOverrideDetails"] = {
    "idTokenGeneration": {
        "claimsToAddOrOverride": {
            "https://aws.amazon.com/tags": {
                "principal_tags": {"TenantID": [tenant_id]}
            }
        }
    },
    "accessTokenGeneration": {
        "claimsToAddOrOverride": {"tenant_id": tenant_id}
    }
}
```

**Trust policy del rol tenant-scoped:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Federated": "arn:aws:iam::111122223333:oidc-provider/cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_EXAMPLE" },
      "Action": ["sts:AssumeRoleWithWebIdentity", "sts:TagSession"],
      "Condition": {
        "StringEquals": {
          "cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_EXAMPLE:aud": "EXAMPLECLIENTID"
        }
      }
    }
  ]
}
```

**Política de datos con `LeadingKeys`:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TenantScopedItemAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query",
        "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"
      ],
      "Resource": "arn:aws:dynamodb:ap-northeast-1:111122223333:table/AppData",
      "Condition": {
        "ForAllValues:StringEquals": {
          "dynamodb:LeadingKeys": ["${aws:PrincipalTag/TenantID}"]
        }
      }
    }
  ]
}
```

**Aislamiento S3 por prefijo:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TenantObjectAccess",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::app-tenant-data/${aws:PrincipalTag/TenantID}/*"
    },
    {
      "Sid": "TenantScopedList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::app-tenant-data",
      "Condition": {
        "StringLike": { "s3:prefix": ["${aws:PrincipalTag/TenantID}/*"] }
      }
    }
  ]
}
```

**Grant KMS por tenant:**
```bash
aws kms create-grant \
  --key-id arn:aws:kms:ap-northeast-1:111122223333:key/<tenant-cmk> \
  --grantee-principal arn:aws:iam::111122223333:role/tenant-scoped-data-access \
  --operations Encrypt Decrypt GenerateDataKey \
  --constraints EncryptionContextEquals={tenant=<tenantId>}
```

**Isolation manager en el handler:**
```python
def handler(event, context):
    jwt_token = event["headers"]["authorization"].removeprefix("Bearer ")
    creds = get_tenant_scoped_credentials(jwt_token)
    ddb = boto3.client(
        "dynamodb",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    return ddb.query(TableName="AppData", ...)
```

**Métrica por tenant vía EMF:**
```python
print(json.dumps({
    "_aws": {
        "CloudWatchMetrics": [{
            "Namespace": "SaaSApp/Usage",
            "Dimensions": [["TenantId", "Operation"]],
            "Metrics": [{"Name": "ItemsProcessed", "Unit": "Count"}]
        }]
    },
    "TenantId": tenant_id,
    "Operation": operation,
    "ItemsProcessed": items
}))
```

### Cifras concretas respaldadas

| Cifra | Valor |
|---|---|
| Máximo de session tags en operación STS | **50** |
| Longitud máxima de clave de tag | **128 caracteres** |
| Longitud máxima de valor de tag | **256 caracteres** |

### Implicaciones de diseño para el middleware eKYC

- El **modelo Bridge es el ajuste natural**: pool para la tabla de casos de onboarding y los documentos S3 de tenants estándar; silo (tabla + CMK dedicada) para tenants regulados o de alto volumen que exijan segregación demostrable ante auditoría.
- El esquema `pk = TENANT#<tenantId>` debe fijarse **desde el día uno**: `LeadingKeys` no es retrofit-able sin migración de datos.
- **Todo GSI de búsqueda de casos eKYC debe llevar `TENANT#<tenantId>` como PK**, o queda fuera del perímetro IAM. Esto colisiona directamente con los beacons de la Ficha 4 (ver implicación cruzada allí).
- Presupuesto de session tags: 50 tags es holgado, pero `TenantID` + `tier` + `jurisdiction` + `role` ya consume 4; mantener el set mínimo y estable.
- El `EncryptionContextEquals={tenant=...}` del grant KMS debe **coincidir exactamente** con el encryption context usado al cifrar (Fichas 2 y 3) — una discrepancia produce `AccessDeniedException` en decrypt, no un fallo de cifrado, lo que la hace difícil de detectar en pruebas.
- El fail-closed del pre-token trigger es un requisito duro para eKYC: un token sin tenant no debe existir jamás.

---

## Ficha 2 — Cifrado de campos PII en DynamoDB con KMS desde Lambda

**URL:** https://dev.to/aws-builders/aws-lambda-pii-handling-in-production-dynamodb-field-encryption-with-kms-3oa6
**Recuperación:** ✅ Exitosa

### Resumen técnico

Artículo práctico (nivel introductorio-intermedio) que muestra el patrón de **cifrado a nivel de campo directamente contra la API de KMS** — no envelope encryption con data keys, sino llamadas `kms:Encrypt` / `kms:Decrypt` sobre el plaintext del campo. El flujo: API Gateway → Lambda → cifra campos sensibles → escribe ciphertext base64 en DynamoDB; en lectura, Lambda descifra explícitamente con la misma clave y el mismo encryption context.

La infraestructura se define en **CDK (Python)**. La CMK se crea con `enable_key_rotation=True` (rotación anual automática: nueva clave para cifrados nuevos, claves antiguas retenidas para descifrar histórico) y `removal_policy=DESTROY` marcado explícitamente como "RETAIN for prod". La Lambda usa Python 3.12, 256 MB, timeout 15s, con la capa de Powertools, y recibe permisos vía los helpers de menor privilegio `pii_table.grant_read_write_data(pii_handler)` y `pii_key.grant_encrypt_decrypt(pii_handler)` — "no wildcards, explicit permissions only".

El punto técnico más relevante es el uso de **EncryptionContext** como AAD (additional authenticated data): `{"purpose": "pii-location-encryption", "service": "pii-service"}`. El contexto se pasa idéntico en `encrypt` y `decrypt`; si no coincide, el descifrado falla. Esto ata criptográficamente el ciphertext a un caso de uso concreto y, además, hace que el contexto aparezca en los eventos de CloudTrail, lo que da trazabilidad por propósito.

El patrón de ítem agrupa varios campos PII en un único JSON antes de cifrar (`{"latitude":..., "longitude":...}` → un solo campo `encrypted_coordinates`), lo que reduce el número de llamadas KMS por operación a una. El ítem queda como `pk = USER#<user_id>`, `sk = LOCATION#<timestamp>`, `encrypted_coordinates = <base64>`.

Trade-offs que la fuente reconoce explícitamente: las llamadas KMS añaden **decenas de milisegundos** de latencia; el tamaño del ítem crece por el base64 del ciphertext; a cambio, el plaintext PII nunca se almacena en DynamoDB, **cada operación de decrypt queda registrada en CloudTrail**, y el acceso es revocable modificando la key policy sin tocar los datos.

La limitación estructural (no señalada por el autor, pero implícita en el diseño): **una llamada KMS por operación de lectura/escritura**, sin caching. Esto no escala a volúmenes altos y es exactamente el problema que resuelve la Ficha 3.

### Fragmentos reutilizables (transcritos)

**CMK en CDK:**
```python
pii_key = kms.Key(
    self,
    "PiiEncryptionKey",
    alias="pii-encryption-key",
    description="KMS key for encrypting PII data (latitude/longitude)",
    enable_key_rotation=True,
    removal_policy=RemovalPolicy.DESTROY,  # RETAIN for prod
)
```

**Lambda + permisos:**
```python
pii_handler = _lambda.Function(
    self, "PiiHandler",
    runtime=_lambda.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=_lambda.Code.from_asset(
        os.path.join(os.path.dirname(__file__), "PIIHandler"),
    ),
    layers=[powertools_layer],
    timeout=Duration.seconds(15),
    memory_size=256,
    environment={
        "POWERTOOLS_SERVICE_NAME": "pii-service",
        "POWERTOOLS_LOG_LEVEL": "INFO",
        "PII_TABLE_NAME": pii_table.table_name,
        "KMS_KEY_ARN": pii_key.key_arn,
        "ALLOWED_ORIGIN": "*",
    }
)

pii_table.grant_read_write_data(pii_handler)
pii_key.grant_encrypt_decrypt(pii_handler)
```

**Cifrado/descifrado con encryption context:**
```python
import json, os, base64
from boto3 import client, resource

TABLE_NAME = os.environ.get("PII_TABLE_NAME")
KMS_KEY_ARN = os.environ.get("KMS_KEY_ARN")

KMS_CLIENT = client('kms')
DDB_RESOURCE = resource('dynamodb')
TABLE = DDB_RESOURCE.Table(TABLE_NAME)

def encrypt_data(plaintext: str) -> str:
    """Encrypt data using KMS and return base64-encoded ciphertext."""
    response = KMS_CLIENT.encrypt(
        KeyId=KMS_KEY_ARN,
        Plaintext=plaintext.encode("utf-8"),
        EncryptionContext={
            "purpose": "pii-location-encryption",
            "service": "pii-service",
        },
    )
    return base64.b64encode(response["CiphertextBlob"]).decode("utf-8")

def decrypt_data(encrypted_data: str) -> str:
    """Decrypt base64-encoded ciphertext using KMS."""
    ciphertext = base64.b64decode(encrypted_data)
    response = KMS_CLIENT.decrypt(
        CiphertextBlob=ciphertext,
        KeyId=KMS_KEY_ARN,
        EncryptionContext={
            "purpose": "pii-location-encryption",
            "service": "pii-service",
        },
    )
    return response["Plaintext"].decode("utf-8")
```

**Escritura del ítem:**
```python
def handle_create_location(event) -> dict:
    """Handle POST /locations - Store encrypted PII location data."""
    event_body = json.loads(event.get('body'))
    user_id = event_body["user_id"]
    latitude = event_body["latitude"]
    longitude = event_body["longitude"]

    coordinates = json.dumps({"latitude": latitude, "longitude": longitude})
    encrypted_coordinates = encrypt_data(coordinates)

    item = {
        "pk": f"USER#{user_id}",
        "sk": f"LOCATION#{timestamp}",
        "encrypted_coordinates": encrypted_coordinates
    }
    TABLE.put_item(Item=item)
```

### Cifras concretas respaldadas

| Concepto | Valor (declarado como "Pricing, February 2026") |
|---|---|
| CMK gestionada por cliente | **1 USD/mes** (prorrateado por hora) |
| Operaciones criptográficas KMS | **0,03 USD por 10.000 requests** |
| Capa gratuita | **20.000 operaciones/mes por región** |
| Coste adicional por rotación de clave | **+1 USD/mes** |
| Rotación automática | cada **365 días** |
| Latencia añadida por llamada KMS | "**tens of milliseconds**" (sin cifra exacta) |
| Config de la Lambda del ejemplo | 256 MB, timeout 15 s, Python 3.12 |

> ⚠️ Los precios provienen de un blog de terceros y deben re-verificarse contra la página oficial de precios de AWS KMS antes de usarse en un modelo financiero.

### Implicaciones de diseño para el middleware eKYC

- **Agrupar campos PII en un único blob cifrado por ítem** (como `encrypted_coordinates`) es la palanca más barata: reduce llamadas KMS de N a 1 por operación. Aplicable a un bloque `identity_document` que agrupe nombre, número de documento, fecha de nacimiento y dirección.
- El coste de rotación (+1 USD/mes por CMK) es despreciable por clave, pero en un modelo **silo con CMK por tenant** escala linealmente: 1.000 tenants = ~2.000 USD/mes solo en existencia de claves, antes de cualquier operación. Esto es un argumento cuantitativo fuerte a favor del **hierarchical keyring / branch keys** (Fichas 3 y 4) frente a CMK-por-tenant.
- El **encryption context es el punto de integración con la Ficha 1**: debe incluir `tenant` para que los grants con `EncryptionContextEquals` funcionen. El ejemplo del artículo (`purpose` + `service`) es insuficiente para multi-tenant — hay que extenderlo a `{"tenant": tenant_id, "purpose": "ekyc-pii", "service": "onboarding"}`.
- El registro en CloudTrail de cada decrypt es un **activo de cumplimiento** para eKYC (trazabilidad de acceso a PII), pero también un generador de volumen: con caching (Ficha 3) se pierde granularidad de auditoría por acceso. Es un trade-off explícito a documentar.
- El patrón tal cual **no es viable a escala**: una llamada KMS síncrona por lectura, con decenas de ms, en un flujo de onboarding con múltiples pasos, acumula latencia y consume cuota compartida de KMS.

---

## Ficha 3 — CachingCryptoMaterialsManager, cache stampede y cifrado por tenant a escala

**URL:** https://aws.amazon.com/blogs/security/caching-kms-data-keys-in-multi-thread-environments-per-tenant-encryption-for-event-driven-systems-at-scale/
**Recuperación:** ✅ Exitosa

### Resumen técnico

Este es el artículo más directamente relevante para el problema de escala del middleware. Documenta un **fallo real del `CachingCryptoMaterialsManager` (CCMM) del AWS Encryption SDK en entornos multi-hilo**: cuando una entrada de caché de data key expira, no hay coordinación entre hilos. "Each thread independently calls `GenerateDataKey` against AWS KMS. Instead of one thread generating a data key while others wait, **N threads create N distinct data keys**."

El daño no se limita al pico de llamadas. Los EDKs (encrypted data keys) excedentes generados durante la fase de cifrado **degradan el ratio de aciertos de caché en el lado de descifrado**, provocando llamadas KMS redundantes adicionales. En el caso de estudio de **NICE Actimize**, esto produjo "a ratio of 30% unique data keys to data records in DynamoDB tables" — casi uno de cada tres registros cifrado con una data key distinta, y "millions of duplicate API calls per hour".

El artículo presenta **dos remedios**:

**Opción A (recomendada por AWS): hierarchical keyring.** Introduce **branch keys almacenados en DynamoDB** como claves de envoltura intermedias entre la CMK de KMS y las data keys. La caché por defecto está diseñada para entornos multi-hilo: un único hilo refresca la entrada mientras los demás siguen usando la entrada aún válida, mediante una **ventana de notificación de pre-expiración de 10 segundos**. Es la misma primitiva que usa la Ficha 4 para DB-ESDK.

**Opción B (implementación de NICE Actimize): `CachedKmsClient`.** Un decorador sobre el `KmsClient` estándar del SDK con dos `LoadingCache` de **Caffeine**:

| Caché | Configuración | Mecanismo |
|---|---|---|
| GenerateDataKey | `refreshAfterWrite` (1 hora por defecto) | Reutiliza la data key para la misma KMS key de tenant |
| Decrypt | `refreshAfterWrite` (1 hora por defecto) | Una sola llamada KMS por EDK único |

La clave del arreglo es la **carga atómica de Caffeine**: "exactly one thread executes the loader function (the actual KMS API call), while all other concurrent threads block and wait for that single result". Esto es precisamente lo que el CCMM no garantiza. `refreshAfterWrite` (frente a `expireAfterWrite`) sirve además contenido rancio durante el refresco, evitando el pico de latencia.

**Aislamiento por tenant:** ambas opciones lo preservan **particionando las cachés por el ARN de la KMS key específica del tenant** como clave de caché, garantizando que "each tenant's encryption materials remain cryptographically isolated". No hay riesgo de cruce de materiales entre tenants siempre que la clave de caché incluya el discriminador de tenant.

**Trade-off de seguridad reconocido:** el caching implica mantener **data keys en plaintext en memoria** durante el TTL. El artículo lo enmarca como un control de seguridad ajustable: "shorter TTLs reduce the window of exposure in the event of a memory dump, while longer TTLs reduce KMS call volume".

### Cifras concretas respaldadas

| Cifra | Valor | Atribución |
|---|---|---|
| Reducción de coste KMS | **77 %** | NICE Actimize, tras implementar caching coordinado (Opción B) |
| Ratio de data keys únicas por registro (antes) | **30 %** | ~1 de cada 3 registros con data key distinta |
| Volumen de llamadas duplicadas (antes) | "**millions of duplicate API calls per hour**" | — |
| Ventana de pre-expiración de la caché por defecto (hierarchical keyring) | **10 segundos** | Opción A |
| TTL por defecto de las cachés Caffeine | **1 hora** (`refreshAfterWrite`) | Opción B |

**Cuotas oficiales de KMS verificadas** (contexto necesario para dimensionar, [Request quotas — AWS KMS](https://docs.aws.amazon.com/kms/latest/developerguide/requests-per-second.html)):

| Cuota | Valor |
|---|---|
| Operaciones criptográficas compartidas (simétricas), us-east-1 / us-west-2 / eu-west-1 | **100.000 req/s** |
| Idem, us-east-2 / ap-southeast-1 / ap-southeast-2 / ap-northeast-1 / eu-central-1 / eu-west-2 | **20.000 req/s** |
| Idem, resto de regiones | **10.000 req/s** |
| Operaciones cubiertas por la cuota compartida | Decrypt, Encrypt, GenerateDataKey, GenerateDataKeyWithoutPlaintext, GenerateMac, GenerateRandom, ReEncrypt, VerifyMac |
| `CreateGrant` / `RetireGrant` / `RevokeGrant` | **50 req/s cada una** (cuotas independientes) |

### Implicaciones de diseño para el middleware eKYC

- **No usar `CachingCryptoMaterialsManager` tal cual en Lambdas con concurrencia alta ni en contenedores multi-hilo.** Si el middleware usa el AWS Encryption SDK, la ruta por defecto debe ser el **hierarchical keyring** (Opción A), que además es la misma primitiva que exige DB-ESDK (Ficha 4) — una sola decisión cubre ambas necesidades.
- El cuello de botella crítico es **`CreateGrant` a 50 req/s**. Si el diseño de la Ficha 1 crea un grant por tenant en caliente durante el onboarding, ese límite se alcanza con ~50 altas de tenant por segundo. Los grants deben crearse en el **flujo de provisioning del tenant**, nunca en el flujo de request.
- El **modelo de concurrencia de Lambda cambia el cálculo**: cada entorno de ejecución Lambda es efectivamente mono-hilo por invocación, así que el stampede clásico intra-proceso es menos agudo — pero se sustituye por un **stampede entre entornos de ejecución** (N entornos fríos = N llamadas `GenerateDataKey`). El hierarchical keyring con branch keys en DynamoDB mitiga esto porque la branch key es compartida y persistente, no efímera por entorno.
- **TTL como parámetro de cumplimiento, no de rendimiento.** Para eKYC (PII de alta sensibilidad), el TTL de 1 hora del caso NICE Actimize probablemente sea demasiado largo. Recomendable parametrizarlo por tier de sensibilidad y documentar la ventana de exposición ante memory dump en el modelo de amenazas.
- Dimensionar contra la cuota regional compartida de KMS: en una región de 10.000 req/s, sin caching y con 1 llamada KMS por operación (patrón de la Ficha 2), el techo de throughput del middleware completo es 10.000 ops/s **compartido con todo lo demás en la cuenta**.
- El ratio de 30% data keys únicas es un **buen indicador de salud a instrumentar**: métrica `unique_data_keys / records_written` por tenant, con alarma si se desvía.

---

## Ficha 4 — AWS Database Encryption SDK y beacons de búsqueda sobre atributos cifrados

**URL:** https://aws.amazon.com/blogs/security/how-to-use-aws-database-encryption-sdk-for-client-side-encryption-and-perform-searches-on-encrypted-attributes-in-dynamodb-tables/
**Recuperación:** ✅ Exitosa (segunda pasada necesaria para extraer el código Java completo)

### Resumen técnico

El **DB-ESDK** es un record encryptor que "encrypts, signs, verifies, and decrypts the records in DynamoDB table" del lado cliente, y habilita **búsquedas sobre datos cifrados mediante beacons** — índices HMAC truncados.

**Acciones por atributo** (`CryptoAction`), configurables individualmente:
- `ENCRYPT_AND_SIGN` — "Encrypts and signs the attributes in each record using a unique encryption key".
- `SIGN_ONLY` — "Adds a digital signature to verify the authenticity of your data". **Obligatorio para partition key y sort key** (no se pueden cifrar).
- `DO_NOTHING` — sin cifrado ni autenticación.

**Tipos de beacon:**
- **Standard beacon** — consultas sobre un único campo fuente con operaciones de igualdad (equals / not-equals). Admite **virtual fields**: campos sintéticos formados concatenando varios campos fuente (p. ej. `FullName` = `firstname` + `lastname`).
- **Compound beacon** — consultas sobre combinaciones de campos cifrados y firmados, habilitando "begins with, contains, between". Se construye a partir de standard beacons previos, con una **lista de `EncryptedPart` con prefijos únicos por campo** (`C-`, `E-`) y un **carácter separador único** (`~`). La consulta se hace entonces con un valor tipo `"C-4567~E-082026"`.

**Infraestructura criptográfica:** requiere una **keystore table** dedicada en DynamoDB (con un `logicalKeyStoreName`) que aloja las **branch keys**. La **Material Providers Library (MPL)** gestiona keyrings y wrapping keys con envelope encryption. El **hierarchical keyring** interpone las branch keys entre la wrapping key de KMS y las data keys, "reducing AWS KMS network calls through caching" — es exactamente la Opción A de la Ficha 3.

**Trade-off de seguridad declarado:** "There are tradeoffs between how efficient your queries are and how much information is indirectly revealed about the distribution of your data." Un beacon más largo reduce colisiones (mejor rendimiento de query) pero filtra más sobre la distribución de los datos.

**Limitación operativa crítica:** no se recomienda configurar beacons sobre tablas existentes, porque **los beacons solo se calculan para registros nuevos**. Combinado con la regla oficial de que **la longitud de beacon no puede cambiarse tras escribir registros**, esto convierte el dimensionado del beacon en una **decisión irreversible de día cero**.

Los beacons se materializan como atributos con prefijo `aws_dbe_b_` y se consultan a través de **GSIs creados sobre esos atributos** (`aws_dbe_b_email-index`, `aws_dbe_b_VirtualNameCardCompound-index`).

### Fragmentos reutilizables (transcritos)

**Creación de la keystore table:**
```java
private static void keyStoreCreateTable(String keyStoreTableName,
                                       String logicalKeyStoreName,
                                       String kmsKeyArn) {
    final KeyStore keystore = KeyStore.builder().KeyStoreConfig(
            KeyStoreConfig.builder()
                    .ddbClient(DynamoDbClient.create())
                    .ddbTableName(keyStoreTableName)
                    .logicalKeyStoreName(logicalKeyStoreName)
                    .kmsClient(KmsClient.create())
                    .kmsConfiguration(KMSConfiguration.builder()
                            .kmsKeyArn(kmsKeyArn)
                            .build())
                    .build()).build();

    keystore.CreateKeyStore(CreateKeyStoreInput.builder().build());
}
```

**Creación de branch key:**
```java
final String branchKeyId = keystore.CreateKey(CreateKeyInput.builder().build()).branchKeyIdentifier();
```

**Configuración de tabla + interceptor:**
```java
final Map<String, CryptoAction> attributeActionsOnEncrypt = new HashMap<>();
attributeActionsOnEncrypt.put("order_id", CryptoAction.SIGN_ONLY);
attributeActionsOnEncrypt.put("order_time", CryptoAction.SIGN_ONLY);
attributeActionsOnEncrypt.put("email", CryptoAction.ENCRYPT_AND_SIGN);
attributeActionsOnEncrypt.put("firstname", CryptoAction.ENCRYPT_AND_SIGN);
attributeActionsOnEncrypt.put("lastname", CryptoAction.ENCRYPT_AND_SIGN);
attributeActionsOnEncrypt.put("last4creditcard", CryptoAction.ENCRYPT_AND_SIGN);
attributeActionsOnEncrypt.put("expirydate", CryptoAction.ENCRYPT_AND_SIGN);

final Map<String, DynamoDbTableEncryptionConfig> tableConfigs = new HashMap<>();
final DynamoDbTableEncryptionConfig config = DynamoDbTableEncryptionConfig.builder()
        .logicalTableName(ddbTableName)
        .partitionKeyName("order_id")
        .sortKeyName("order_time")
        .attributeActionsOnEncrypt(attributeActionsOnEncrypt)
        .keyring(kmsKeyring)
        .search(SearchConfig.builder()
                .writeVersion(1)
                .versions(beaconVersions)
                .build())
        .build();
tableConfigs.put(ddbTableName, config);

DynamoDbEncryptionInterceptor encryptionInterceptor = DynamoDbEncryptionInterceptor.builder()
        .config(DynamoDbTablesEncryptionConfig.builder()
                .tableEncryptionConfigs(tableConfigs)
                .build())
        .build();

final DynamoDbClient ddb = DynamoDbClient.builder()
        .overrideConfiguration(
                ClientOverrideConfiguration.builder()
                        .addExecutionInterceptor(encryptionInterceptor)
                        .build())
        .build();
```

**Virtual field (concatenación de campos):**
```java
List<VirtualPart> virtualPartList = new ArrayList<>();
VirtualPart firstnamePart = VirtualPart.builder().loc("firstname").build();
VirtualPart lastnamePart  = VirtualPart.builder().loc("lastname").build();
virtualPartList.add(firstnamePart);
virtualPartList.add(lastnamePart);

VirtualField fullnameField = VirtualField.builder()
    .name("FullName")
    .parts(virtualPartList)
    .build();
```

**Standard beacons:**
```java
StandardBeacon emailBeacon = StandardBeacon.builder()
  .name("email").length(15).build();
StandardBeacon last4creditcardBeacon = StandardBeacon.builder()
  .name("last4creditcard").length(15).build();
StandardBeacon expirydateBeacon = StandardBeacon.builder()
  .name("expirydate").length(15).build();
StandardBeacon fullnameBeacon = StandardBeacon.builder()
  .name("FullName").length(15).build();
```

**Compound beacon:**
```java
List<EncryptedPart> encryptedPartList_card = new ArrayList<>();
EncryptedPart last4creditcardEncryptedPart = EncryptedPart.builder()
  .name("last4creditcard").prefix("C-").build();
EncryptedPart expirydateEncryptedPart = EncryptedPart.builder()
  .name("expirydate").prefix("E-").build();
encryptedPartList_card.add(last4creditcardEncryptedPart);
encryptedPartList_card.add(expirydateEncryptedPart);

CompoundBeacon CardCompoundBeacon = CompoundBeacon.builder()
  .name("CardCompound")
  .split("~")
  .encrypted(encryptedPartList_card)
  .build();
```

**BeaconVersion y key source:**
```java
beaconVersions.add(
        BeaconVersion.builder()
                .standardBeacons(standardBeaconList)
                .compoundBeacons(compoundBeaconList)
                .version(1)
                .keyStore(keyStore)
                .keySource(BeaconKeySource.builder()
                        .single(SingleKeyStore.builder()
                                .keyId(branchKeyId)
                                .cacheTTL(6000)
                                .build())
                        .build())
                .build()
);
```

**Hierarchical keyring:**
```java
final MaterialProviders matProv = MaterialProviders.builder()
        .MaterialProvidersConfig(MaterialProvidersConfig.builder().build())
        .build();
CreateAwsKmsHierarchicalKeyringInput keyringInput = CreateAwsKmsHierarchicalKeyringInput.builder()
        .branchKeyId(branchKeyId)
        .keyStore(keyStore)
        .ttlSeconds(60)
        .build();
final IKeyring kmsKeyring = matProv.CreateAwsKmsHierarchicalKeyring(keyringInput);
```

**Query sobre standard beacon (igualdad):**
```java
QueryRequest queryRequest = QueryRequest.builder()
  .tableName(ddbTableName)
  .indexName("aws_dbe_b_email-index")
  .keyConditionExpression("#e = :e")
  .expressionAttributeNames(expressionAttributesNames)   // "#e" -> "email"
  .expressionAttributeValues(expressionAttributeValues)  // ":e" -> "mary.major@example.com"
  .build();
```

**Query sobre compound beacon:**
```java
expressionAttributesNames.put("#PKName", "FullName");
expressionAttributesNames.put("#SKName", "CardCompound");
expressionAttributeValues.put(":PKValue", AttributeValue.builder().s("JohnDoe").build());
expressionAttributeValues.put(":SKValue", AttributeValue.builder().s("C-4567~E-082026").build());

QueryRequest queryRequest = QueryRequest.builder()
  .tableName(ddbTableName)
  .indexName("aws_dbe_b_VirtualNameCardCompound-index")
  .keyConditionExpression("#PKName = :PKValue and #SKName = :SKValue")
  .expressionAttributeNames(expressionAttributesNames)
  .expressionAttributeValues(expressionAttributeValues)
  .build();
```

**Secuencia de despliegue declarada por el artículo:**
1. Crear clave simétrica de KMS
2. Crear la keystore table en DynamoDB
3. Crear branch key y beacon key en la keystore
4. Configurar la tabla de aplicación con las attribute actions
5. Definir y configurar beacons (standard y compound)
6. Crear los GSIs sobre los atributos de beacon
7. Inicializar keyring e interceptor
8. Insertar y consultar registros

### Cifras concretas respaldadas

**Del artículo:**

| Parámetro | Valor en el ejemplo |
|---|---|
| `StandardBeacon.length` | **15** (los cuatro beacons) |
| `BeaconVersion.version` | 1 |
| `SearchConfig.writeVersion` | 1 |
| `CreateAwsKmsHierarchicalKeyringInput.ttlSeconds` | **60** |
| `SingleKeyStore.cacheTTL` | **6000** |
| Separador de compound beacon | `~` |
| Prefijos de partes cifradas | `C-`, `E-` |

**Verificación oficial de la semántica de `length`** ([Choosing a beacon length — AWS Database Encryption SDK](https://docs.aws.amazon.com/database-encryption-sdk/latest/devguide/choosing-beacon-length.html)):

> La longitud de beacon se mide en **bits**, no en caracteres. El artículo no lo aclara; `length(15)` = **15 bits**.

| Guía oficial | Valor |
|---|---|
| Fórmula de colisiones | `número de colisiones = Población × 2^(−longitud de beacon)` |
| Rango recomendado de colisiones | `2 ≤ colisiones < √(Población)` |
| Fórmula simple (datos uniformes) | `b = log₂(p) − 1` |
| Población mínima requerida | **16 valores únicos** |
| Ejemplo con población 100.000 | rango recomendado **8–15 bits**; a 15 bits ≈ **1,5 falsos positivos por valor** y **66 %** de probabilidad de mismo valor; a 14 bits ≈ **6,1 falsos positivos**, 33 %; a 8 bits ≈ **316 falsos positivos** (máximo recomendado) |
| Irreversibilidad | La longitud de beacon **no puede cambiarse tras escribir registros** con ese beacon |

### Implicaciones de diseño para el middleware eKYC

- **Colisión de diseño con la Ficha 1 (crítica):** el patrón de la Ficha 1 exige que todo GSI tenga `TENANT#<tenantId>` como partition key para quedar cubierto por `dynamodb:LeadingKeys`. Los GSIs de beacon (`aws_dbe_b_email-index`) tienen el **beacon** como PK. Resolución: construir **compound beacons o virtual fields que incorporen el tenant ID como primera parte**, de modo que el GSI de beacon siga siendo tenant-scoped. Es la decisión arquitectónica de mayor riesgo del middleware y debe cerrarse antes de escribir el primer registro.
- **El dimensionado de beacon es irreversible.** Para eKYC hay que estimar la población por campo y por partición: `email` en un tenant grande puede tener 10⁶ valores únicos (→ `b ≈ 19` bits), mientras `nationality` tiene ~200 (→ `b ≈ 7`). Usar `length(15)` uniformemente, como hace el artículo, es un valor de demo, no una recomendación.
- El **hierarchical keyring con branch keys es la respuesta conjunta** al problema de escala de la Ficha 3 y al requisito de búsqueda de la Ficha 4. Una branch key por tenant en la keystore table da aislamiento criptográfico por tenant sin el coste de 1 USD/mes/CMK.
- `SIGN_ONLY` obligatorio en PK/SK significa que **`TENANT#<tenantId>` y el `caseId` viajan en claro** en DynamoDB. Aceptable (son identificadores opacos), pero hay que asegurar que no se codifique PII en las claves — p. ej. nunca `sk = DOC#<numero_documento>`.
- Los beacons **filtran distribución**. Para campos de baja cardinalidad y alta sensibilidad en eKYC (nacionalidad, estado PEP, nivel de riesgo AML), el beacon revela más de lo aceptable. Recomendación: **no indexar por beacon los campos de baja cardinalidad**; resolver esas consultas por otra vía (agregados precalculados, filtrado en cliente tras query por tenant).
- Los beacons **no se aplican retroactivamente**: cualquier campo que pueda necesitar búsqueda en el futuro debe tener beacon **desde el inicio**, aunque no se use.

---

## Ficha 5 — Step Functions Standard vs Express: costes y workflows anidados

**URL:** https://aws.amazon.com/blogs/compute/building-cost-effective-aws-step-functions-workflows/
**Recuperación:** ✅ Exitosa

### Resumen técnico

El artículo contrapone los **dos modelos de facturación** de Step Functions y demuestra el patrón de **workflows anidados** como punto óptimo entre coste y garantías.

**Standard Workflows** se facturan **por transición de estado**: 0,025 USD por 1.000 transiciones (0,000025 USD/transición). Ofrecen semántica **exactly-once**, soportan los patrones `.WaitForTaskToken` (callback) y `.sync` (job-run), y permiten esperas largas — el artículo cita esperas de aprobación humana de hasta **1 año**, con el tiempo de espera **no facturable** (solo se paga la transición).

**Express Workflows** tienen facturación **dual**: coste por ejecución (0,000001 USD por request) **más** coste por duración, redondeado a los 100 ms más cercanos y cobrado por GB-hora de memoria en bloques de 64 MB. Duración máxima **5 minutos**, semántica **at-least-once**, y throughput de **hasta 100.000 transiciones de estado por segundo**.

**Comparación cuantitativa** sobre un workflow de e-commerce ejecutado 1.000 veces:

- **Standard puro:** 17 transiciones por ejecución → `(17 × 1.000) × 0,000025 = 0,42 USD`
- **Express puro:** duración media 11.300 ms → coste de duración `(11.300 ÷ 100) × 0,0000001042 = 0,0000117746 USD` → total `(0,000001 + 0,0000117746) × 1.000 = 0,01 USD` → **reducción del 98 %**
- **Anidado (Standard padre + Express hijo):** padre con 8 transiciones → `8 × 1.000 × 0,000025 = 0,20 USD`; hijo Express → `(0,000001 + 0,0000013546) × 1.000 = 0,0002 USD` → **total 0,20 USD por 1.000 ejecuciones**, es decir **~52 % de ahorro frente al Standard puro**, conservando las garantías de Standard en el orquestador.

Dato clave del patrón anidado: **"No additional charge for starting a nested workflow"** — arrancar un workflow hijo desde el padre no consume transición adicional facturada.

> ⚠️ El artículo afirma que Standard tiene "no limit" de duración máxima. Esto es **impreciso**: la documentación oficial fija **1 año**. Ver sección de verificación.

### Cifras concretas respaldadas

| Concepto | Valor |
|---|---|
| Standard — precio por transición | **0,025 USD / 1.000 transiciones** (= 0,000025 USD c/u) |
| Express — precio por request | **0,000001 USD** |
| Express — granularidad de facturación por duración | redondeo a **100 ms**, bloques de **64 MB**, cobro por GB-hora |
| Express — duración máxima | **5 minutos** |
| Express — throughput | hasta **100.000 transiciones de estado/segundo** |
| Standard — semántica | exactly-once |
| Express — semántica | at-least-once |
| Ejemplo Standard puro (1.000 ejec., 17 transiciones) | **0,42 USD** |
| Ejemplo Express puro (1.000 ejec., 11.300 ms medios) | **0,01 USD** → **98 % de ahorro** |
| Ejemplo anidado (Standard 8 transiciones + Express) | **0,20 USD / 1.000 ejec.** → **~52 % de ahorro** |
| Coste de arrancar workflow anidado | **0 USD adicional** |
| Espera de aprobación humana con `.WaitForTaskToken` | hasta **1 año**, no facturable |

### Implicaciones de diseño para el middleware eKYC

- **El patrón anidado es el ajuste correcto para eKYC**, no Express puro. El flujo de onboarding necesita esperas largas (revisión manual de documentos, respuesta de un proveedor externo de verificación, aprobación de compliance) y garantías exactly-once sobre acciones no idempotentes (crear cuenta, notificar al buró de crédito). Eso exige Standard en el orquestador.
- **Los pasos automatizados de alto volumen van en Express hijos**: OCR de documento, detección de liveness, extracción de campos MRZ, scoring de riesgo, deduplicación. Todos caben cómodamente en los 5 minutos y son idempotentes o pueden hacerse idempotentes.
- **Express es at-least-once** → todo Task invocado desde un Express hijo debe ser **idempotente por diseño**. En eKYC esto significa claves de idempotencia derivadas del `caseId` + `stepId`, y escrituras condicionales en DynamoDB (ver Ficha 6).
- Express **no soporta `.waitForTaskToken` ni `.sync` ni Distributed Map ni Activities** (verificado en docs oficiales). Cualquier integración con revisión humana o job largo debe vivir en el padre Standard.
- **Optimización de transiciones en el padre:** cada estado del Standard cuesta. Colapsar cadenas de `Pass`/`Choice` triviales y mover la lógica de ramificación al hijo Express reduce la factura linealmente. Bajar de 17 a 8 transiciones fue la mitad del ahorro del ejemplo.
- Express **requiere CloudWatch Logs** para tener historial inspeccionable, lo que añade coste de logs no incluido en el cálculo del artículo — relevante en eKYC, donde la trazabilidad es obligatoria y el volumen de logs es alto.

---

## Ficha 6 — Motor de orquestación dinámica con DynamoDB y Lambda

**URL:** https://aws.amazon.com/blogs/database/build-a-dynamic-workflow-orchestration-engine-with-amazon-dynamodb-and-aws-lambda/
**Recuperación:** ✅ Exitosa

### Resumen técnico

Alternativa a Step Functions para casos donde el **grafo de tareas es dinámico** (definido en runtime por el cliente, no en una ASL estática). El motor materializa un **DAG en DynamoDB** y lo hace avanzar con DynamoDB Streams + Lambda, sin polling.

**Modelo de datos.** Clave compuesta: **PK = `run_id`** (identificador único de ejecución de workflow), **SK = `task_id`** (identificador de tarea dentro del workflow). Cada ítem-tarea lleva: `status` (PENDING / COMPLETED / ERROR), `version` (para optimistic locking), `locked` (YES/NO), `payload`, `retry_enabled`, `task_output`, `in_dependencies` (lista de tareas que deben completarse antes), `out_dependencies` (lista de tareas que dependen de esta), `function_name` (Lambda a invocar), `ttl`, `task_duration`, `error_message`.

**Flujo de ejecución (10 pasos).** El cliente envía la definición del workflow; los payloads iniciales suben a S3 y cada tarea se persiste en DynamoDB con `status=PENDING`. DynamoDB Streams captura el cambio y dispara la **monitor function**, que evalúa si la tarea está lista: comprueba `status == PENDING` y que todas las `in_dependencies` estén `COMPLETED`. Si lo está, marca `locked=YES` e invoca **asíncronamente** la **execute function**, que a su vez invoca **síncronamente** la task function. Esta recupera el payload completo de S3, procesa y devuelve el output. La execute function reintenta ante error, o almacena el resultado en S3, actualiza `status=COMPLETED`, `locked=NO`, y **propaga la ruta S3 del output a cada tarea dependiente** en DynamoDB — lo que dispara un nuevo evento de Stream y hace avanzar el DAG. El proceso itera hasta que todas las tareas alcancen estado terminal.

Este diseño "eliminates the need for polling" y asegura que "tasks start as soon as their dependencies are met".

**Concurrencia.** El problema central es que "multiple tasks might be running and completing in parallel". Se resuelve con **optimistic locking sobre el atributo `version`**: leer capturando la versión actual, actualizar con un condition check de que la versión no cambió, y reintentar si falla. "If two Lambda functions try to update the same task simultaneously, only one will succeed. The other function must retry with the updated version." A esto se suma el flag `locked` como protección de concurrencia adicional (verificar `locked=NO` antes de poner `locked=YES`).

**Payloads grandes.** Para superar el límite de **400 KB por ítem de DynamoDB**, payloads y outputs se almacenan en S3 y DynamoDB guarda solo la ruta.

**Limpieza.** TTL en DynamoDB y lifecycle en S3, ambos a **10 días**. Capacidad **on-demand** para escalar automáticamente sin preprovisionar.

**Resultados medidos** en un workflow de análisis financiero de 9 tareas: ejecución secuencial 530 s frente a **186 s con orquestación paralela — 65 % de reducción**. La ruta crítica queda dominada por la tarea 3 (102 s), la consolidación (tarea 8, 27 s) y el análisis final (tarea 9, 57 s). Demuestra patrones **fan-out** (7 tareas iniciales en paralelo) y **fan-in** (tarea 8 espera 3 inputs; tarea 9 espera 5).

### Fragmentos reutilizables (transcritos)

**Ítem-tarea en DynamoDB:**
```json
{
  "run_id": "12345678-1234-1234-1234-123456789012",
  "task_id": "3",
  "status": "PENDING",
  "version": 1,
  "locked": "NO",
  "payload": "s3://payload-bucket/12345678-1234-1234-1234-123456789012/3/payload.json",
  "retry_enabled": "true",
  "in_dependencies": [
    {
      "in_dependency_task_id": "1",
      "in_dependency_status": "COMPLETED",
      "task_output": "s3://payload-bucket/12345678-1234-1234-1234-123456789012/1/output.json"
    },
    { "in_dependency_task_id": "2" }
  ],
  "out_dependencies": [
    { "out_dependency_task_id": "4" },
    { "out_dependency_task_id": "5" }
  ],
  "function_name": "ExecuteAgentFunction",
  "ttl": 1718826000
}
```

**Definición de workflow (array JSON):**
```json
[
    {
        "task_id": "5",
        "payload": { ... },
        "retry_enabled": "true",
        "in_dependencies": [
            { "in_dependency_task_id": "3" }
        ],
        "out_dependencies": [
            { "out_dependency_task_id": "8" }
        ]
    }
]
```

**Configuración del event source mapping (DynamoDB Streams):**
```
Batch size: 1          # "to minimize latency between task completion and dependent task execution"
Parallelization factor: 10
```

### Cifras concretas respaldadas

| Concepto | Valor |
|---|---|
| Límite de tamaño de ítem DynamoDB (motivo del offload a S3) | **400 KB** |
| Batch size del event source mapping | **1** (para minimizar latencia) |
| Parallelization factor | **10** |
| TTL de ítems DynamoDB | **10 días** |
| Lifecycle de objetos S3 | **10 días** |
| Modo de capacidad | on-demand |
| Ejemplo: ejecución secuencial | **530 segundos** |
| Ejemplo: ejecución orquestada en paralelo | **186 segundos** |
| Mejora de rendimiento | **65 % de reducción** |
| Tarea 3 (más larga en paralelo) | 102 s |
| Tarea 8 (consolidación) | 27 s |
| Tarea 9 (análisis final) | 57 s |
| Workflow de ejemplo | 9 tareas (fan-out de 7, fan-in de 3 y de 5) |

### Implicaciones de diseño para el middleware eKYC

- **Este patrón es la respuesta al requisito "dinámico" del middleware.** Si cada tenant define su propio flujo de onboarding (qué documentos, qué verificaciones, en qué orden, qué proveedor externo), una ASL estática por tenant no escala. El DAG en DynamoDB permite que la definición del flujo sea **dato del tenant**, no código.
- **Modelo híbrido recomendado:** Step Functions Standard (Ficha 5) como esqueleto de las fases mayores y garante de exactly-once, y este motor DynamoDB para el **sub-grafo dinámico de verificaciones** dentro de una fase. Evita reimplementar reintentos, timeouts y auditoría desde cero.
- **Colisión de esquema con la Ficha 1 (importante):** la PK propuesta es `run_id`, sin tenant. Bajo el modelo de `dynamodb:LeadingKeys`, esto **rompe el aislamiento IAM**. Adaptación obligatoria: **PK = `TENANT#<tenantId>#RUN#<runId>`**, SK = `TASK#<taskId>`. Sin este cambio, cualquier tenant con credenciales del rol puede leer los runs de otro.
- **El offload a S3 encaja con eKYC**: las imágenes de documentos, selfies y respuestas de proveedores exceden con creces los 400 KB. Los objetos S3 deben ir bajo el prefijo `${TenantID}/` de la política de la Ficha 1, y cifrarse con la clave del tenant (Fichas 2/3).
- **TTL de 10 días es incompatible con eKYC.** Las obligaciones de retención KYC/AML suelen exigir **5–10 años**. El TTL debe eliminarse de los ítems de caso o fijarse en función de la jurisdicción del tenant; conservar el TTL corto solo para artefactos intermedios efímeros.
- **`retry_enabled=false` es el mecanismo para operaciones no idempotentes** — llamadas facturables a proveedores externos de verificación de identidad, o notificaciones a autoridades. Mapear explícitamente cada tarea eKYC a este flag.
- **Riesgo operativo del `locked` flag:** si una Lambda muere tras poner `locked=YES` pero antes de completar, la tarea queda bloqueada indefinidamente. El artículo no aborda esto. Añadir un `lock_expires_at` con reaper, o un heartbeat.
- `parallelization factor = 10` sobre el Stream requiere revisar el reparto: DynamoDB Streams ordena por partition key, por lo que un `run_id` (o `TENANT#...#RUN#...`) concentrado puede serializar el avance de ese workflow concreto.

---

# Advertencias y verificación de cifras

## Resumen de veredictos

| # | Afirmación del spec original | Veredicto | Evidencia |
|---|---|---|---|
| 1 | Ahorro **72,5 %** en Express Workflows | ❌ **NO CONFIRMADO** — la fuente no menciona esta cifra | La fuente 5 da **98 %** (Express puro) y **~52 %** (patrón anidado) |
| 2 | Reducción **77 %** de coste KMS con CCMM | ⚠️ **CONFIRMADO CON MATIZ GRAVE** — el 77 % es real pero **no se logró con CCMM** | Fuente 3 |
| 3 | Reducción **90 %** de tokens y **85 %** de latencia con Prompt Caching en Bedrock | ⚠️ **PARCIAL** — ninguna de las 6 fuentes lo menciona; confirmado externamente pero **mal formulado** | Página de producto AWS Bedrock |
| 4 | Límite de **3008 MB** de memoria Lambda para AVX-512 | ❌ **CONTRADICHO** — doblemente incorrecto | Docs oficiales Lambda |
| 5 | Retención de historial **90 días** en Standard Workflows | ✅ **CONFIRMADO** | Docs oficiales Step Functions |
| 6 | Duración máxima **1 año** | ✅ **CONFIRMADO** (para Standard) | Docs oficiales Step Functions |

---

## Detalle por afirmación

### 1. Ahorro del 72,5 % en Express Workflows — ❌ NO CONFIRMADO

La cifra **72,5 % no aparece en ninguna de las seis fuentes**. La fuente 5 ([Building cost-effective AWS Step Functions workflows](https://aws.amazon.com/blogs/compute/building-cost-effective-aws-step-functions-workflows/)) documenta dos ahorros distintos, ninguno próximo a 72,5 %:

- **Standard puro → Express puro:** 0,42 USD → 0,01 USD = **98 %** de reducción.
- **Standard puro → anidado (Standard padre + Express hijo):** 0,42 USD → 0,20 USD = **52,4 %** de reducción.

**Hipótesis de origen del error:** 72,5 % podría ser un promedio, una interpolación entre ambos escenarios, o una cifra de otra fuente no citada. **No debe usarse.** Además, cualquier porcentaje de ahorro es **totalmente dependiente del workflow concreto** — de su número de transiciones y de su duración media. El propio ejemplo lo demuestra: el ahorro cae de 98 % a 52 % solo por conservar 8 transiciones Standard en el padre. Recomendación: sustituir por un cálculo propio con el número real de transiciones y la duración media del flujo eKYC.

### 2. Reducción del 77 % de coste KMS con CCMM — ⚠️ CONFIRMADO CON MATIZ GRAVE

La cifra del **77 %** es correcta y está respaldada por la fuente 3: NICE Actimize logró "a 77% reduction in AWS KMS costs".

**Pero la atribución del spec es errónea y peligrosa.** El artículo describe el `CachingCryptoMaterialsManager` como **la causa del problema**, no la solución: es precisamente el CCMM el que, al expirar entradas en entornos multi-hilo, deja que N hilos llamen a `GenerateDataKey` simultáneamente y generen N data keys distintas. El 77 % se obtuvo con la **Opción B** — un `CachedKmsClient` custom con cachés Caffeine y carga atómica — que **sustituye** el comportamiento del CCMM.

**Riesgo de diseño concreto:** si el spec del middleware dice "usar CCMM para lograr 77 % de ahorro", el equipo implementará exactamente lo que el artículo identifica como el bug. La redacción debe corregirse a: *"Evitar el CCMM en entornos concurrentes; usar hierarchical keyring (recomendación AWS) o caching con carga atómica; el caso NICE Actimize reporta 77 % de reducción de coste KMS con este último enfoque."*

### 3. Prompt Caching en Bedrock: 90 % tokens / 85 % latencia — ⚠️ PARCIAL, Y MAL FORMULADO

**Ninguna de las seis fuentes de referencia menciona Bedrock ni prompt caching.** Es un dato huérfano en el spec.

Verificado externamente: la página de producto [Amazon Bedrock Prompt Caching](https://aws.amazon.com/bedrock/prompt-caching/) afirma que el prompt caching puede *"reduce costs by up to 90% and latency by up to 85% for supported models"*.

**Tres correcciones necesarias:**

1. **El 90 % es reducción de *coste*, no de *tokens*.** El spec dice "reducción del 90 % de tokens", lo cual es incorrecto: el número de tokens de entrada no baja — los tokens cacheados se facturan con **descuento del 90 %**. La distinción importa para el dimensionado de cuotas y de límites de contexto, que no mejoran.
2. **"Up to" no es un valor esperado.** Ambos son techos alcanzables solo con reutilización de prefijo casi perfecta.
3. **La documentación oficial no da porcentajes.** [Prompt caching for faster model inference](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) solo describe la funcionalidad como orientada a "reduce inference response latency and input token costs", sin cifras. Los porcentajes proceden de material de marketing.

**Restricciones operativas relevantes** (de la documentación oficial, a la fecha de consulta), imprescindibles para saber si el ahorro es siquiera alcanzable:

| Parámetro | Valor |
|---|---|
| TTL de caché — Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 | **5 min** (por defecto), **1 hora** (opcional) |
| TTL de caché — Claude Opus 4.6, 3.7 Sonnet, 3.5 Sonnet v2, Opus 4 | **5 min** únicamente |
| TTL de caché — OpenAI GPT-5.6 (Sol, Terra, Luna) | **30 min** |
| Mínimo de tokens por checkpoint — Opus 4.5/4.6, Haiku 4.5, Sonnet 4.5 | **4.096** |
| Mínimo de tokens por checkpoint — Sonnet 4.6, 3.7 Sonnet, 3.5 Sonnet v2, Opus 4 | **1.024** |
| Mínimo de tokens por checkpoint — OpenAI GPT-5.6 | **1.024** |
| Checkpoints máximos por request | **4** |
| Descuento en lecturas de caché (GPT-5.6) | **90 %** vs. tokens de entrada no cacheados |
| Sobrecoste de escritura de caché (GPT-5.6) | **1,25×** la tarifa de entrada no cacheada |
| Sobrecoste de escritura de caché (GPT-5.5 y anteriores) | sin coste adicional |

**Implicación para eKYC:** con TTL de 5 minutos y mínimo de 1.024–4.096 tokens por checkpoint, el ahorro solo se materializa si el middleware mantiene un **prefijo de prompt estable y voluminoso** (instrucciones de extracción documental, esquema de salida, ejemplos few-shot) y **suficiente frecuencia de invocación** para que el caché no expire entre peticiones. En un tenant de bajo volumen, el prompt caching puede resultar **neto negativo** por el sobrecoste de escritura.

### 4. Límite de 3008 MB de memoria Lambda para AVX-512 — ❌ CONTRADICHO (doble error)

Esta afirmación es incorrecta en **ambos** de sus componentes.

**a) El límite de memoria de Lambda no es 3008 MB.** Según [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html), el rango es **128 MB a 10.240 MB en incrementos de 1 MB**. La cifra de 3.008 MB fue el máximo histórico **hasta diciembre de 2020**; lleva más de cinco años obsoleta. Un spec que la fije como límite dejaría rendimiento y CPU sobre la mesa: en Lambda la asignación de vCPU es proporcional a la memoria, por lo que capar a 3008 MB también capa la CPU disponible.

**b) No existe ningún requisito de memoria vinculado a AVX-512.** La documentación de [Using AVX2 vectorization in Lambda](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-avx2.html) documenta **AVX2** ("a vectorization extension to the Intel x86 instruction set that can perform single instruction multiple data (SIMD) instructions over vectors of 256 bits") y **no menciona AVX-512 en absoluto**, ni ninguna restricción de tamaño de memoria asociada a extensiones vectoriales. Además: "Lambda arm64 uses NEON SIMD architecture and does not support the x86 AVX2 extensions", y el uso de AVX2 no tiene coste adicional.

**Conclusión:** la afirmación parece fusionar dos datos no relacionados y desactualizados. Debe eliminarse del spec. Si el middleware depende de aceleración SIMD (plausible en procesamiento de imagen de documentos o extracción de features biométricas), lo correcto es: (i) fijar arquitectura **x86_64** explícitamente si se requiere AVX2, (ii) **no asumir disponibilidad de AVX-512** sin verificación en runtime, y (iii) dimensionar la memoria por perfil de rendimiento medido, no por un límite inexistente.

**Cuotas reales de Lambda verificadas:**

| Cuota | Valor oficial |
|---|---|
| Memoria de función | **128 MB – 10.240 MB**, incrementos de 1 MB |
| Timeout máximo | **900 segundos (15 min)** |
| Almacenamiento efímero `/tmp` | **512 MB – 10.240 MB**, incrementos de 1 MB |
| Paquete de despliegue comprimido | **50 MB** |
| Paquete descomprimido (incl. capas y runtimes custom) | **250 MB** |
| Imagen de contenedor (descomprimida, todas las capas) | **10 GB** |
| Payload de invocación síncrona | **6 MB** (request y response, cada uno) |
| Payload de invocación asíncrona | **1 MB** |
| Ejecuciones concurrentes (por defecto, por región) | **1.000** (ampliable a decenas de miles) |
| Variables de entorno (tamaño agregado) | **4 KB** |
| Burst de concurrencia | **1.000 entornos de ejecución cada 10 segundos, por función** |

### 5. Retención de historial de 90 días en Standard Workflows — ✅ CONFIRMADO

Confirmado por [Step Functions service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html) y por [Choosing workflow type](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html): el historial de ejecución de Standard Workflows se retiene **90 días tras el cierre de la ejecución**, y puede **reducirse a 30 días** mediante solicitud de soporte.

**Matiz relevante para eKYC:** Express Workflows **no tienen** esta retención — requieren CloudWatch Logs habilitado para cualquier inspección del historial. Si el middleware adopta el patrón anidado de la Ficha 5, **el historial de los hijos Express solo existe en CloudWatch Logs**, con su propia política de retención (configurable, por defecto indefinida) y su propio coste. Para trazabilidad KYC/AML, **90 días es insuficiente**: se requiere exportación explícita del historial a almacenamiento de largo plazo (S3 con Object Lock, o Glacier) antes de que expire.

### 6. Duración máxima de 1 año — ✅ CONFIRMADO (para Standard)

Confirmado por [Step Functions service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html) y [Choosing workflow type](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html): **Standard = 1 año ("One year")**, **Express = 5 minutos ("Five minutes")**.

**Advertencia sobre la fuente 5:** el blog de AWS afirma que Standard tiene *"no limit"* de duración máxima. Esto **contradice la documentación oficial** y es impreciso o está desactualizado. **Prevalece la documentación oficial: 1 año.** Es un ejemplo de por qué las cifras de blogs de AWS deben verificarse contra `docs.aws.amazon.com` antes de entrar en un spec.

---

## Cuotas oficiales verificadas — tabla de referencia

### AWS Step Functions ([service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html), [choosing workflow type](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html))

| Cuota | Standard | Express |
|---|---|---|
| Duración máxima de ejecución | **1 año** | **5 minutos** |
| Retención de historial | **90 días** tras cierre (reducible a 30 por solicitud) | Ilimitado dentro de la ventana de 5 min; **requiere CloudWatch Logs** para inspección |
| Tamaño máximo de historial | **25.000 eventos** por ejecución | Sin límite |
| Payload de entrada/salida | **256 KiB** (UTF-8) | **256 KiB** (UTF-8) |
| Tamaño de definición de state machine | **1 MB** (cuota **dura**) | **1 MB** (cuota dura) |
| Ejecuciones abiertas | **1.000.000** por cuenta y región (soft) | No sujeto a este límite |
| Tasa de transición de estado | Sujeta a cuotas de throttling | **Sin límite** |
| Base de facturación | Nº de transiciones de estado | Nº de ejecuciones + duración + memoria |
| Semántica de ejecución | **Exactly-once** | Asíncrono: **at-least-once** / Síncrono: **at-most-once** |
| Integraciones de servicio | Todas | Todas **excepto** `.sync` (job-run) y `.waitForTaskToken` (callback) |
| Distributed Map | Soportado | **No soportado** |
| Activities | Soportado | **No soportado** |

> **Nota:** el límite de **25.000 eventos de historial por ejecución** en Standard no aparecía en el spec y es una restricción real para eKYC: un workflow con muchos reintentos, o con un bucle sobre N documentos, puede agotarlo. AWS documenta el patrón de [iniciar nuevas ejecuciones para evitar la cuota de historial](https://docs.aws.amazon.com/step-functions/latest/dg/bp-history-limit.html).

### AWS Lambda ([Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html))

Ver tabla completa en el punto 4 de arriba. Titulares: **memoria 128 MB – 10.240 MB**, **timeout 900 s**, **`/tmp` 512 MB – 10.240 MB**, **payload síncrono 6 MB / asíncrono 1 MB**, **concurrencia por defecto 1.000/región**, **burst 1.000 entornos cada 10 s por función**.

### AWS KMS ([Request quotas](https://docs.aws.amazon.com/kms/latest/developerguide/requests-per-second.html))

| Cuota | Valor |
|---|---|
| Operaciones criptográficas compartidas (simétricas) — us-east-1, us-west-2, eu-west-1 | **100.000 req/s** |
| Idem — us-east-2, ap-southeast-1, ap-southeast-2, ap-northeast-1, eu-central-1, eu-west-2 | **20.000 req/s** |
| Idem — resto de regiones | **10.000 req/s** |
| `CreateGrant` / `RetireGrant` / `RevokeGrant` | **50 req/s** cada una (independientes de la cuota compartida) |

### AWS Database Encryption SDK ([Choosing a beacon length](https://docs.aws.amazon.com/database-encryption-sdk/latest/devguide/choosing-beacon-length.html))

| Parámetro | Valor |
|---|---|
| Unidad de `beacon length` | **bits** (no caracteres — el blog de la Ficha 4 no lo aclara) |
| Fórmula de colisiones | `colisiones = Población × 2^(−longitud)` |
| Rango recomendado | `2 ≤ colisiones < √(Población)`; fórmula simple `b = log₂(p) − 1` |
| Población mínima | **16 valores únicos** |
| Mutabilidad | La longitud **no puede cambiarse** tras escribir registros |

---

## Advertencias transversales sobre calidad de las fuentes

1. **Dos de las seis fuentes no son documentación oficial de AWS.** La Ficha 1 (hidekazu-konishi.com) y la Ficha 2 (dev.to) son blogs de terceros. Sus patrones son sólidos y coherentes con la guía oficial de SaaS de AWS, pero **sus cifras de precios y cuotas no son autoritativas**. Los precios de KMS de la Ficha 2 ("February 2026") deben re-verificarse contra la página oficial de precios antes de entrar en cualquier modelo financiero.

2. **Los blogs oficiales de AWS también contienen imprecisiones.** La fuente 5 afirma "no limit" para la duración de Standard Workflows, contradiciendo la cuota oficial de 1 año. Regla de trabajo: `docs.aws.amazon.com` prevalece sobre `aws.amazon.com/blogs` en cualquier discrepancia de cuotas.

3. **Los valores numéricos en el código de ejemplo son valores de demo, no recomendaciones.** `StandardBeacon.length(15)`, `ttlSeconds(60)`, `cacheTTL(6000)`, `memory_size=256`, TTL de 10 días — todos son ilustrativos. Copiarlos a producción sin dimensionar es un error, y en el caso de `beacon length` es un error **irreversible**.

4. **Tres conflictos de diseño no resueltos entre fuentes**, que deben cerrarse antes de implementar:
   - **GSI de beacon vs. `dynamodb:LeadingKeys`** (Ficha 4 vs. Ficha 1) — el aislamiento IAM y la búsqueda cifrada compiten por la partition key del índice.
   - **PK = `run_id` sin tenant** (Ficha 6 vs. Ficha 1) — rompe el aislamiento IAM tal cual está publicado.
   - **CCMM como causa vs. como solución** (Ficha 3 vs. redacción del spec) — ver punto 2 de la verificación.

5. **Cifras del spec sin respaldo en las fuentes citadas:** el 72,5 % de Express y los porcentajes de Bedrock Prompt Caching **no provienen de ninguna de las seis fuentes**. El 65 % de mejora de la Ficha 6 y el 98 %/52 % de la Ficha 5 sí están respaldados, pero son específicos de los workloads de ejemplo y **no transferibles** a eKYC sin medición propia.

**Sources:**
- [Multi-Tenant SaaS Architecture Guide — hidekazu-konishi.com](https://hidekazu-konishi.com/entry/aws_saas_multi_tenant_architecture_guide.html)
- [AWS Lambda PII Handling in Production — dev.to](https://dev.to/aws-builders/aws-lambda-pii-handling-in-production-dynamodb-field-encryption-with-kms-3oa6)
- [Caching KMS data keys in multi-thread environments — AWS Security Blog](https://aws.amazon.com/blogs/security/caching-kms-data-keys-in-multi-thread-environments-per-tenant-encryption-for-event-driven-systems-at-scale/)
- [How to use AWS Database Encryption SDK for client-side encryption — AWS Security Blog](https://aws.amazon.com/blogs/security/how-to-use-aws-database-encryption-sdk-for-client-side-encryption-and-perform-searches-on-encrypted-attributes-in-dynamodb-tables/)
- [Building cost-effective AWS Step Functions workflows — AWS Compute Blog](https://aws.amazon.com/blogs/compute/building-cost-effective-aws-step-functions-workflows/)
- [Build a dynamic workflow orchestration engine with DynamoDB and Lambda — AWS Database Blog](https://aws.amazon.com/blogs/database/build-a-dynamic-workflow-orchestration-engine-with-amazon-dynamodb-and-aws-lambda/)
- [Step Functions service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html)
- [Choosing workflow type in Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html)
- [Starting new executions to avoid reaching the history quota](https://docs.aws.amazon.com/step-functions/latest/dg/bp-history-limit.html)
- [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [Using AVX2 vectorization in Lambda](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-avx2.html)
- [AWS KMS request quotas](https://docs.aws.amazon.com/kms/latest/developerguide/requests-per-second.html)
- [Choosing a beacon length — AWS Database Encryption SDK](https://docs.aws.amazon.com/database-encryption-sdk/latest/devguide/choosing-beacon-length.html)
- [Prompt caching for faster model inference — Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Amazon Bedrock Prompt Caching (product page)](https://aws.amazon.com/bedrock/prompt-caching/)

agentId: a6fea802e389a59f9 (use SendMessage with to: 'a6fea802e389a59f9', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 96531
tool_uses: 26
duration_ms: 2021283</usage>