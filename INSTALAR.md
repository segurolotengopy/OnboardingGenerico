# Instalación del proyecto en este directorio

El repositorio completo se entrega comprimido como `OnboardingGenerico.tar.gz`, con el historial de Git ya inicializado y el remoto configurado. Se entrega así porque el puente de archivos entre la sesión y su equipo transfiere un máximo de 50 archivos por operación, y el proyecto tiene 265.

## Descompresión

Desde este mismo directorio (`~/Onboarding-Generico`):

```bash
cd ~/Onboarding-Generico
tar -xzf OnboardingGenerico.tar.gz --strip-components=1
rm OnboardingGenerico.tar.gz
```

La opción `--strip-components=1` coloca el contenido directamente aquí, sin crear un nivel adicional de carpeta. Si prefiere el proyecto en un subdirectorio propio, omita esa opción.

## Verificación inmediata

```bash
git log --oneline          # debe mostrar el commit inicial
git remote -v              # debe apuntar a OnboardingGenerico.git

PYTHONPATH=src python3 tests/run_smoke.py    # 23 comprobaciones, sin dependencias externas
```

Si tiene `pytest` disponible:

```bash
PYTHONPATH=src python3 -m pytest tests -q    # 362 pruebas
```

Y una comprobación que vale la pena hacer, porque demuestra que la parte más delicada del dominio funciona de verdad:

```bash
PYTHONPATH=src python3 scripts/verify_mrz.py --ejemplo td3
```

Debe mostrar los cinco dígitos de control del pasaporte de ejemplo de la OACI como correctos.

## Publicación en GitHub

El remoto ya está configurado. Falta únicamente autenticarse y empujar:

```bash
git push -u origin main
```

Si el repositorio remoto ya tiene contenido —por ejemplo un `README` creado al abrirlo—, reconcilie antes:

```bash
git pull --rebase origin main
git push -u origin main
```

## Entorno de desarrollo

```bash
make install        # entorno virtual con dependencias de desarrollo
make verificar      # lint, verificación de tipos y pruebas
make ayuda          # catálogo completo de tareas
```

Los extras de nube son opcionales y se instalan solo cuando se va a trabajar contra esa nube: `make install-aws` o `make install-gcp`. El núcleo del dominio funciona sin ninguno de los dos.

## Por dónde empezar a leer

`docs/00-indice.md` contiene el mapa de lectura por rol. Si va directo a lo esencial: `README.md`, luego `docs/02-arquitectura.md`, y después `docs/20-fe-de-erratas-del-spec-original.md`, que documenta las ocho afirmaciones de la especificación de origen que resultaron falsas al verificarlas.
