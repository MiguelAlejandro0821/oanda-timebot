# OANDA Time Bot (Render)

Este paquete permite desplegar el bot en Render como **Web Service** (1 worker) que mantiene un endpoint `/` para healthcheck y corre el bot en segundo plano.

## Pasos rápidos (Render)

1. Crea un repositorio en GitHub y sube estos archivos.
2. En Render, **New +** → **Web Service** → Conecta tu repo.
3. **Runtime**: Docker.
4. **Branch**: main (o la tuya).
5. **Environment**: selecciona **Docker**.
6. En **Environment Variables**, añade:
   - OANDA_ENV=practice
   - OANDA_TOKEN=<tu token>
   - OANDA_ACCOUNT_ID=<tu account id>
   - INSTRUMENT=EUR_USD
   - UNITS=10000
   - TZ=America/New_York
   - ENTRY_HOUR=16
   - ENTRY_MINUTE=55
   - ROBUST_ENTRY=true
   - TP_PIPS=10
   - SL_PIPS=0
   - ONE_PER_DAY=true
   - ONLY_WEEK=true
   - CLOSE_AT_HOUR=17
   - CLOSE_AT_MINUTE=10
   - PIP_MODE=Auto (FX)
   - CUSTOM_PIP=0.0001
7. Deploy.

> Nota: Los servicios web gratuitos pueden hibernar y los workers de fondo suelen requerir plan de pago. Si necesitas 24/5 sin hibernación, usa un plan que no duerma o un VPS.
