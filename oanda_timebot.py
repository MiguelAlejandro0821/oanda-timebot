# oanda_timebot.py
# Bot horario para OANDA v20 que replica la lógica del Pine Script dado.
# Requisitos:
#   pip install requests pytz python-dateutil
# Variables de entorno mínimas:
#   OANDA_ENV=practice|live
#   OANDA_TOKEN=<token>
#   OANDA_ACCOUNT_ID=<account id>

import os
import time
import json
import requests
from datetime import datetime, timedelta
import pytz

# ---------------------------
# CONFIG BÁSICA
# ---------------------------
OANDA_ENV       = os.getenv("OANDA_ENV", "practice")       # "practice" o "live"
OANDA_TOKEN     = os.getenv("OANDA_TOKEN", "PON_AQUI_TU_TOKEN")
ACCOUNT_ID      = os.getenv("OANDA_ACCOUNT_ID", "PON_AQUI_TU_ACCOUNT_ID")

INSTRUMENT      = os.getenv("INSTRUMENT", "EUR_USD")
UNITS           = int(os.getenv("UNITS", "10000"))         # tamaño de posición (positivo = long)

# ---------------------------
# PARÁMETROS (mapeo 1:1 con tu Pine)
# ---------------------------
tz              = os.getenv("TZ", "America/New_York")      # Zona horaria de la entrada
entryHour       = int(os.getenv("ENTRY_HOUR", "16"))       # 0-23
entryMinute     = int(os.getenv("ENTRY_MINUTE", "55"))     # 0-59
robustEntry     = os.getenv("ROBUST_ENTRY", "true").lower() in ("1","true","yes","y")
tpPips          = int(os.getenv("TP_PIPS", "10"))          # >=1
slPips          = int(os.getenv("SL_PIPS", "0"))           # 0 = sin SL
onePerDay       = os.getenv("ONE_PER_DAY", "true").lower() in ("1","true","yes","y")
onlyWeek        = os.getenv("ONLY_WEEK", "true").lower() in ("1","true","yes","y")

closeAtHour     = int(os.getenv("CLOSE_AT_HOUR", "17"))
closeAtMinute   = int(os.getenv("CLOSE_AT_MINUTE", "10"))

pipMode         = os.getenv("PIP_MODE", "Auto (FX)")       # "Auto (FX)" | "Personalizado"
customPip       = float(os.getenv("CUSTOM_PIP", "0.0001")) # usado si pipMode = Personalizado

# ---------------------------
# ENDPOINTS
# ---------------------------
BASE_URL = "https://api-fxpractice.oanda.com" if OANDA_ENV == "practice" else "https://api-fxtrade.oanda.com"
HEADERS  = {
    "Authorization": f"Bearer {OANDA_TOKEN}",
    "Content-Type": "application/json"
}

# ---------------------------
# UTILIDADES
# ---------------------------
def get_tz():
    try:
        return pytz.timezone(tz)
    except Exception:
        return pytz.timezone("UTC")

def local_now():
    return datetime.now(get_tz())

def today_key(dt_local: datetime) -> str:
    return dt_local.strftime("%Y%m%d")

def is_weekday(dt_local: datetime) -> bool:
    # Lunes=0 ... Domingo=6
    return dt_local.weekday() <= 4

def pip_size_for(instrument: str) -> float:
    if pipMode.lower().startswith("auto"):
        return 0.01 if instrument.endswith("JPY") else 0.0001
    return customPip

def price_decimals(pip: float) -> int:
    # Para OANDA suele haber "fractional pip" (5 decimales en EUR_USD, 3 en JPY)
    return 5 if pip <= 0.0001 else 3

def round_price(px: float, decimals: int) -> str:
    fmt = "{:0." + str(decimals) + "f}"
    return fmt.format(px)

def get_pricing(instrument: str):
    params = {"instruments": instrument}
    r = requests.get(f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/pricing", headers=HEADERS, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    prices = data.get("prices", [])
    if not prices:
        raise RuntimeError("No hay precios para el instrumento.")
    p = prices[0]
    bid = float(p["bids"][0]["price"])
    ask = float(p["asks"][0]["price"])
    return bid, ask

def has_open_long(instrument: str) -> bool:
    url = f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/positions/{instrument}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    pos = r.json().get("position", {})
    long_units = float(pos.get("long", {}).get("units", "0"))
    return long_units > 0

def open_long_market(instrument: str, units: int, tp_pips: int, sl_pips: int):
    # Calculamos TP/SL con precio ask actual
    bid, ask = get_pricing(instrument)
    pip = pip_size_for(instrument)
    dec = price_decimals(pip)

    tp_price = ask + tp_pips * pip
    tp_s = round_price(tp_price, dec)

    sl_s = None
    if sl_pips and sl_pips > 0:
        sl_price = ask - sl_pips * pip
        sl_s = round_price(sl_price, dec)

    order = {
        "order": {
            "instrument": instrument,
            "units": str(units),            # positivo = long
            "type": "MARKET",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "takeProfitOnFill": {"price": tp_s}
        }
    }
    if sl_s:
        order["order"]["stopLossOnFill"] = {"price": sl_s}

    r = requests.post(f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/orders",
                      headers=HEADERS, data=json.dumps(order), timeout=10)
    r.raise_for_status()
    return r.json()

def force_close_long(instrument: str):
    url = f"{BASE_URL}/v3/accounts/{ACCOUNT_ID}/positions/{instrument}/close"
    payload = {"longUnits": "ALL"}
    r = requests.put(url, headers=HEADERS, data=json.dumps(payload), timeout=10)
    # Si no hay posición, puede devolver 404; lo tratamos como "ya cerrado"
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 404:
        return {"closed": "none"}
    r.raise_for_status()
    return r.json()

# ---------------------------
# LÓGICA PRINCIPAL
# ---------------------------
def run():
    print(f"[INFO] Iniciando bot OANDA ({OANDA_ENV}) en {INSTRUMENT}, tz={tz}")
    print(f"[INFO] Parámetros: entry={entryHour:02d}:{entryMinute:02d}, robust={robustEntry}, TP={tpPips}p, SL={slPips}p, "
          f"onePerDay={onePerDay}, onlyWeek={onlyWeek}, close={closeAtHour:02d}:{closeAtMinute:02d}, units={UNITS}")

    last_trade_date = None   # yyyymmdd en tz local
    entry_triggered_today = False

    # Para el modo no-robusto: evitar múltiples triggers dentro del mismo minuto
    last_checked_minute_key = None

    while True:
        try:
            now = local_now()
            today = today_key(now)

            # Reset diario
            if last_trade_date != today:
                entry_triggered_today = False
                last_checked_minute_key = None

            # Reglas de día hábil
            if onlyWeek and not is_weekday(now):
                # Pero igual podemos cerrar forzosamente si quedó algo abierto
                maybe_force_close(now)
                time.sleep(1)
                continue

            # Cierre forzoso a la hora configurada
            maybe_force_close(now)

            # Si ya hay posición abierta, no abrimos otra (regla "no abrir hasta que cierre")
            if has_open_long(INSTRUMENT):
                time.sleep(1)
                continue

            # Máx. 1 operación por día
            if onePerDay and entry_triggered_today:
                time.sleep(1)
                continue

            # ¿Se cumple la condición de entrada horaria?
            if should_enter_now(now, robustEntry, entryHour, entryMinute, last_checked_minute_key):
                # Disparar entrada
                print(f"[INFO] Abriendo LONG {INSTRUMENT} @ {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                resp = open_long_market(INSTRUMENT, UNITS, tpPips, slPips)
                print(f"[OK] Orden enviada: {json.dumps(resp)[:400]}...")

                entry_triggered_today = True
                last_trade_date = today

                # Evitar re-disparo en el mismo minuto en modo no-robusto
                last_checked_minute_key = minute_key(now)

            else:
                # Actualizar last_checked_minute_key para el modo exacto
                last_checked_minute_key = minute_key(now)

        except requests.HTTPError as e:
            print(f"[HTTP ERROR] {e} | body={getattr(e.response, 'text', '')[:300]}")
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")

        time.sleep(1)  # bucle 1 Hz

def minute_key(dt_local: datetime) -> str:
    return dt_local.strftime("%Y%m%d%H%M")

def should_enter_now(now_local: datetime, robust: bool, hh: int, mm: int, last_min_key: str) -> bool:
    tzinfo = get_tz()
    target = tzinfo.localize(datetime(now_local.year, now_local.month, now_local.day, hh, mm, 0))

    if robust:
        # Dispara una vez cuando el reloj pasa la hora objetivo (>= target)
        return now_local >= target and minute_key(now_local) != minute_key(target - timedelta(minutes=1))
    else:
        # Modo "exacto": solo dentro del mismo minuto hh:mm, y que no se haya disparado ya en este minuto
        if now_local.hour == hh and now_local.minute == mm:
            curr_min_key = minute_key(now_local)
            return curr_min_key != last_min_key
        return False

def maybe_force_close(now_local: datetime):
    # Si estamos en el minuto de cierre forzoso y hay posición, la cerramos.
    if now_local.hour == closeAtHour and now_local.minute == closeAtMinute:
        if has_open_long(INSTRUMENT):
            print(f"[INFO] Cierre forzoso {INSTRUMENT} @ {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            resp = force_close_long(INSTRUMENT)
            print(f"[OK] Cierre forzoso respuesta: {json.dumps(resp)[:400]}")

if __name__ == "__main__":
    run()
