# vnum_monitor

Detecta números virtuales gratuitos nuevos en 5 sitios y los manda a un webhook de Discord.

## Sitios monitoreados
- receive-smss.com
- receivesms.co
- smsfree24.com
- quackr.io
- onlinesim.io

## Variables de entorno (Render → Environment)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `DISCORD_WEBHOOK` | ✅ sí | URL del webhook de Discord |
| `REDIS_URL` | ❌ opcional | Internal URL de Redis en Render (persistencia entre reinicios) |
| `CHECK_INTERVAL` | ❌ opcional | Segundos entre ciclos (default: 60) |

## Cómo obtener el webhook de Discord
1. Discord → tu servidor → canal → Editar canal → Integraciones → Webhooks → Nuevo Webhook
2. Copiar URL del webhook
3. Pegarlo en Render como `DISCORD_WEBHOOK`

## Deploy en Render
1. Subir este repo a GitHub
2. render.com → New → Blueprint → conectar repo
3. Agregar `DISCORD_WEBHOOK` en Environment
4. (Opcional) New → Redis → Free → copiar Internal URL como `REDIS_URL`
