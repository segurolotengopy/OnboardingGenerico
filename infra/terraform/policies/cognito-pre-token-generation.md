# Trigger de generacion de token de Cognito (evento V2.0)

Este documento explica la pieza de la que depende **todo** el modelo ABAC de AWS. Terraform crea el
user pool, el rol y las politicas; la correccion del aislamiento depende de este codigo.

## Que hace y por que importa

El trigger se ejecuta justo antes de emitir el token y le inyecta un claim especial:

```
https://aws.amazon.com/tags  ->  { "principal_tags": { "TenantID": ["<tenant>"] } }
```

STS lee ese claim durante `AssumeRoleWithWebIdentity` y lo convierte en **session tags**. A partir de
ahi, `${aws:PrincipalTag/TenantID}` esta disponible en las politicas de IAM, y es lo que consumen
`dynamodb:LeadingKeys`, el scoping por prefijo de S3 y la condicion de `kms:EncryptionContext:tenant`.

Sin este trigger, la cadena se rompe **en silencio**: la federacion sigue funcionando, el usuario
obtiene credenciales, y todas las politicas de datos empiezan a denegar sin un mensaje que explique
por que.

## Requisitos duros

1. **`lambda_version = "V2_0"`.** Solo el evento V2 admite `claimsAndScopeOverrideDetails` y, con el,
   `principal_tags`. El evento V1 no puede hacer esto.
2. **La trust policy del rol debe permitir `sts:TagSession` ademas de `sts:AssumeRoleWithWebIdentity`.**
   Es el fallo mas comun del patron: sin esa accion, los tags se descartan sin error.
3. **Fallo cerrado.** Si el usuario no tiene tenant asignado, **no se emite token**. Nunca devuelva un
   token sin `TenantID`, ni con un valor por defecto, ni con cadena vacia.
4. **El tenant nunca viene del cliente.** Se lee del atributo del usuario en el pool o de una fuente de
   verdad del lado servidor. Un `tenant_id` recibido en la peticion es un intento de escalada, no un
   dato.

## Fragmento del trigger

```python
"""Trigger de generacion de token (evento V2.0) del user pool de Cognito.

Inyecta el tenant como principal tag para que STS lo convierta en session tag.
Falla cerrado: sin tenant, no hay token.
"""


class TenantNotAssignedError(Exception):
    """El usuario no tiene tenant. No debe emitirse token."""


def _resolve_tenant_id(event: dict) -> str:
    attributes = event["request"]["userAttributes"]
    tenant_id = attributes.get("custom:tenant_id", "").strip()

    if not tenant_id:
        # Fallo cerrado: se propaga la excepcion y Cognito no emite el token.
        raise TenantNotAssignedError(event["userName"])

    return tenant_id


def handler(event: dict, context) -> dict:
    tenant_id = _resolve_tenant_id(event)

    event["response"]["claimsAndScopeOverrideDetails"] = {
        "idTokenGeneration": {
            "claimsToAddOrOverride": {
                # STS lee este claim y lo convierte en session tags.
                "https://aws.amazon.com/tags": {
                    "principal_tags": {"TenantID": [tenant_id]}
                }
            }
        },
        "accessTokenGeneration": {
            "claimsToAddOrOverride": {"tenant_id": tenant_id}
        },
    }

    return event
```

## Trust policy correspondiente

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/cognito-idp.REGION.amazonaws.com/USER_POOL_ID"
      },
      "Action": [
        "sts:AssumeRoleWithWebIdentity",
        "sts:TagSession"
      ],
      "Condition": {
        "StringEquals": {
          "cognito-idp.REGION.amazonaws.com/USER_POOL_ID:aud": "APP_CLIENT_ID"
        },
        "ForAllValues:StringEquals": {
          "sts:TransitiveTagKeys": ["TenantID"]
        }
      }
    }
  ]
}
```

## Limites y advertencias

| Aspecto | Valor o consecuencia |
|---|---|
| Session tags por operacion de STS | **50** |
| Longitud maxima de clave de tag | **128 caracteres** |
| Longitud maxima de valor de tag | **256 caracteres** |
| Tags recomendados | `TenantID` (obligatorio) y, como mucho, `tier` y `jurisdiction` |

- **`TenantID` distingue mayusculas de minusculas** y debe coincidir **exactamente** con el prefijo de
  las claves de DynamoDB, con el prefijo de objeto de S3 y con el valor del encryption context de KMS.
  Una diferencia de mayusculas produce `AccessDenied` en tiempo de ejecucion, nunca en el despliegue.
- **No meta PII en un tag.** Los session tags aparecen en CloudTrail. `TenantID` debe ser un
  identificador opaco.
- **Mantenga el conjunto de tags minimo y estable.** Agregar un tag obliga a revisar todas las
  politicas que usan `ForAllValues:` sobre `sts:TransitiveTagKeys`.
- **Este patron no tiene equivalente en GCP.** Lo mas cercano es Workload Identity Federation con
  `attribute.tenant`, que gobierna a que **recursos** accede la identidad, no a que **filas** dentro de
  una base de datos. Ver `modules/gcp/identity/README.md`.

## Como se prueba que funciona

Una frontera que no se ha intentado romper es una frontera que no se sabe si funciona. Pruebas minimas:

1. Usuario del tenant A intenta `Query` con `PK = TENANT#B` -> debe recibir `AccessDenied`.
2. Usuario del tenant A intenta `GetObject` sobre `B/caso/doc.jpg` -> debe recibir `AccessDenied`.
3. Usuario del tenant A intenta `Decrypt` de un blob cifrado con encryption context `tenant=B` ->
   debe recibir `AccessDenied`.
4. Usuario sin `custom:tenant_id` intenta autenticarse -> **no debe recibir token**.
5. Se retira `sts:TagSession` de la trust policy en un entorno de prueba -> todas las operaciones de
   datos deben empezar a denegar. Si alguna sigue funcionando, esa politica no esta usando el tag.
