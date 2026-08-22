# Modulo `gcp/observability`

## Que crea

- **Bucket de logs** con retencion explicita y **sinks** hacia el (auditoria) y hacia Cloud Storage
  (retencion de anios).
- **Data Access audit logs** opcionales sobre Firestore, Cloud Storage, Cloud KMS y Secret Manager.
- **Metricas basadas en logs**: desalineacion de alcance de tenant y fallos de descifrado.
- **Politicas de alerta**: desalineacion de tenant, ejecuciones fallidas del workflow, 5xx de Cloud Run
  y fallos de descifrado.
- **Exclusion** de las sondas de salud del bucket por defecto.

## Advertencias

- 🔴 **Los Data Access audit logs estan apagados por defecto** (salvo BigQuery). Sin ellos no hay traza
  de quien leyo datos de que tenant. En AWS los data events de CloudTrail tambien estan apagados por
  defecto, asi que hay paridad en el olvido — pero aqui pesa mas: **como GCP no puede prevenir el
  acceso cruzado entre tenants, la deteccion es la unica capa que queda**.
- **Evite declarar `google_project_iam_audit_config` en dos modulos a la vez.** Este modulo y
  `gcp/identity` pueden crearlo; deje activo solo uno con `enable_audit_config`, o Terraform peleara
  por la propiedad del recurso en cada `apply`.
- **Los Data Access audit logs cuestan.** Sobre Firestore en alto volumen no es despreciable. Use
  filtros de exclusion para el ruido, pero **nunca excluya accesos a datos de tenant**.
- **La metrica de desalineacion de tenant depende del codigo.** Terraform crea la metrica y la alerta;
  si el middleware no emite la entrada `jsonPayload.event = "tenant_scope_mismatch"`, la alerta jamas
  se disparara y dara una falsa sensacion de cobertura.
- **Los fallos de descifrado son una senal buena y mala a la vez.** Buena porque significa que el
  Associated Data esta atajando un acceso con el tenant equivocado; mala porque alguien llego a
  intentarlo. Trate cada pico como incidente.
- **Retenciones:** `_Required` (Admin Activity, System Event, Policy Denied) retiene **400 dias y no es
  configurable** — supera a los 90 dias de historial de eventos de CloudTrail. `_Default` de un
  proyecto retiene 30 dias por defecto y admite de 1 a 3.650. En carpetas y organizaciones **no es
  configurable**.
- **Instrumente con OpenTelemetry.** Es el denominador comun entre Cloud Trace y X-Ray; usar el SDK
  propio de cada nube duplica el trabajo de instrumentacion y rompe la portabilidad del hexagono.
- **Cloud Trace no tiene equivalente exacto al mapa de servicios de X-Ray** ni a X-Ray Insights.
- **El modelo de metricas es distinto**: Cloud Monitoring parte del recurso, no de dimensiones libres
  como CloudWatch. Las metricas por tenant se construyen con `label_extractors` sobre logs
  estructurados, no emitiendo dimensiones arbitrarias.
- Entrada de log: **256 KiB** (512 KiB en auditoria), practicamente igual que CloudWatch.
