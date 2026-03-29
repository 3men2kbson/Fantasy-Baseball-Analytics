from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response, JSONResponse
import httpx, os, math, time
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Fantasy Baseball Analytics API", version="1.0.0")

# ─── CORS — debe ir PRIMERO antes de cualquier ruta ───────────────────────────
ALLOWED_ORIGINS = [
    "https://3men2kbson.github.io",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ─── CORS en respuestas de error (FastAPI no las cubre por defecto) ────────────
@app.middleware("http")
async def add_cors_on_error(request: Request, call_next):
    origin = request.headers.get("origin", "")
    response = await call_next(request)
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"]      = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"]     = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
        response.headers["Access-Control-Allow-Headers"]     = "*"
    return response

# ─── CONFIG ───────────────────────────────────────────────────────────────────
YAHOO_CLIENT_ID     = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI  = os.getenv("YAHOO_REDIRECT_URI", "http://localhost:8000/auth/callback")
FRONTEND_URL        = os.getenv("FRONTEND_URL", "http://localhost:5173")
YAHOO_BASE_URL      = "https://fantasysports.yahooapis.com/fantasy/v2"
YAHOO_AUTH_URL      = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL     = "https://api.login.yahoo.com/oauth2/get_token"

TOKEN_STORE: dict = {}

# ─── HEALTHCHECK ──────────────────────────────────────────────────────────────
@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {
        "status":   "online",
        "service":  "Fantasy Baseball Analytics API",
        "version":  "1.0.0",
        "frontend": FRONTEND_URL,
        "docs":     "/docs",
    }

# ─── AUTH ─────────────────────────────────────────────────────────────────────
@app.get("/auth/login")
async def auth_login():
    if not YAHOO_CLIENT_ID:
        raise HTTPException(400, "YAHOO_CLIENT_ID no configurado.")
    params = {
        "client_id":     YAHOO_CLIENT_ID,
        "redirect_uri":  YAHOO_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid fspt-r",
        "nonce":         str(int(time.time())),
    }
    return RedirectResponse(f"{YAHOO_AUTH_URL}?{urlencode(params)}")


@app.get("/auth/callback")
async def auth_callback(code: str, state: str = None):
    import base64
    creds = base64.b64encode(
        f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            YAHOO_TOKEN_URL,
            headers={
                "Authorization":  f"Basic {creds}",
                "Content-Type":   "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": YAHOO_REDIRECT_URI,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(400, f"Error intercambiando token: {resp.text}")

    tokens = resp.json()
    TOKEN_STORE["access_token"]  = tokens["access_token"]
    TOKEN_STORE["refresh_token"] = tokens.get("refresh_token", "")
    TOKEN_STORE["expires_at"]    = time.time() + tokens.get("expires_in", 3600)

    return Response(
        content=f"""<!DOCTYPE html>
<html>
<head><title>Autenticado</title></head>
<body>
<script>
  if (window.opener) {{
    window.opener.postMessage('yahoo_auth_success', '*');
    window.close();
  }} else {{
    window.location.href = '{FRONTEND_URL}/';
  }}
</script>
<p>Autenticado. Cerrando ventana...</p>
</body>
</html>""",
        media_type="text/html",
    )


@app.get("/auth/status")
async def auth_status():
    if not TOKEN_STORE.get("access_token"):
        return {"authenticated": False}
    if time.time() >= TOKEN_STORE.get("expires_at", 0) - 60:
        await _refresh_token()
    return {
        "authenticated": True,
        "expires_in": max(0, int(TOKEN_STORE.get("expires_at", 0) - time.time())),
    }


async def _refresh_token():
    import base64
    creds = base64.b64encode(
        f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
    ).decode()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            YAHOO_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": TOKEN_STORE.get("refresh_token", ""),
            },
        )
    if resp.status_code == 200:
        tokens = resp.json()
        TOKEN_STORE["access_token"] = tokens["access_token"]
        TOKEN_STORE["expires_at"]   = time.time() + tokens.get("expires_in", 3600)
        if "refresh_token" in tokens:
            TOKEN_STORE["refresh_token"] = tokens["refresh_token"]


# ─── YAHOO API HELPER ─────────────────────────────────────────────────────────
async def yahoo_get(path: str) -> dict:
    if not TOKEN_STORE.get("access_token"):
        raise HTTPException(401, "No autenticado.")
    if time.time() >= TOKEN_STORE.get("expires_at", 0) - 60:
        await _refresh_token()
    url = f"{YAHOO_BASE_URL}{path}?format=json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {TOKEN_STORE['access_token']}"},
            timeout=15.0,
        )
    if resp.status_code == 401:
        await _refresh_token()
        raise HTTPException(401, "Token expirado, reintenta.")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Yahoo API error: {resp.text[:300]}")
    return resp.json()


# ─── LEAGUES ──────────────────────────────────────────────────────────────────
@app.get("/api/leagues")
async def get_leagues():
    try:
        data = await yahoo_get("/users;use_login=1/games;game_codes=mlb/leagues")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error obteniendo ligas: {str(e)}")

    leagues = []
    try:
        users     = data["fantasy_content"]["users"]
        user_data = users["0"]["user"]
        games     = user_data[1]["games"]

        for i in range(games["count"]):
            game_entry   = games[str(i)]["game"]
            # game_entry[1] puede ser dict o lista según la versión de Yahoo API
            game_meta    = game_entry[1]
            if isinstance(game_meta, list):
                game_meta = {k: v for d in game_meta for k, v in d.items()}

            game_leagues = game_meta.get("leagues", {})

            # También puede venir como lista
            if isinstance(game_leagues, list):
                game_leagues = {k: v for d in game_leagues for k, v in d.items()}

            for j in range(game_leagues.get("count", 0)):
                lg_entry = game_leagues[str(j)]["league"]
                # league puede ser lista o dict
                lg = lg_entry[0] if isinstance(lg_entry, list) else lg_entry
                leagues.append({
                    "league_key":   lg.get("league_key", ""),
                    "league_id":    lg.get("league_id", ""),
                    "name":         lg.get("name", "Liga sin nombre"),
                    "season":       lg.get("season", ""),
                    "num_teams":    lg.get("num_teams", 0),
                    "current_week": lg.get("current_week"),
                    "scoring_type": lg.get("scoring_type"),
                })
    except (KeyError, TypeError, IndexError) as e:
        raise HTTPException(500, f"Error parseando ligas: {str(e)} | Raw: {str(data)[:600]}")

    return {"leagues": leagues}

# ─── STANDINGS ────────────────────────────────────────────────────────────────
@app.get("/api/league/{league_key}/standings")
async def get_standings(league_key: str):
    try:
        data = await yahoo_get(f"/league/{league_key}/standings")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error obteniendo standings: {str(e)}")

    standings = []
    try:
        league_data = data["fantasy_content"]["league"]
        teams_data  = league_data[1]["standings"][0]["teams"]
        num_teams   = teams_data["count"]

        for i in range(num_teams):
            team     = teams_data[str(i)]["team"]
            info     = team[0]
            standing = team[1]["team_standings"]

            name     = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), "Unknown")
            team_key = next((x["team_key"] for x in info if isinstance(x, dict) and "team_key" in x), "")
            logo     = next((x["team_logos"][0]["team_logo"]["url"]
                             for x in info if isinstance(x, dict) and "team_logos" in x), "")

            outcomes    = standing.get("outcome_totals", {})
            wins        = int(outcomes.get("wins", 0))
            losses      = int(outcomes.get("losses", 0))
            ties        = int(outcomes.get("ties", 0))
            rank        = int(standing.get("rank", i + 1))
            pts         = float(standing.get("points_for", 0))
            total_games = wins + losses + ties
            win_pct     = (wins + ties * 0.5) / total_games if total_games > 0 else 0.0

            standings.append({
                "team_key":      team_key,
                "name":          name,
                "logo":          logo,
                "rank":          rank,
                "wins":          wins,
                "losses":        losses,
                "ties":          ties,
                "win_pct":       round(win_pct, 3),
                "points_for":    pts,
                "playoff_prob":  _calc_playoff_prob(rank, num_teams, wins, losses),
                "champion_prob": _calc_champion_prob(rank, num_teams, wins, losses),
            })
    except (KeyError, TypeError, IndexError) as e:
        raise HTTPException(500, f"Error parseando standings: {str(e)}")

    return {"standings": sorted(standings, key=lambda x: x["rank"])}


def _calc_playoff_prob(rank, num_teams, wins, losses):
    playoff_spots = max(2, num_teams // 2 - 1)
    total         = wins + losses
    win_rate      = wins / total if total > 0 else 0.5
    x             = (playoff_spots - rank) * 0.8 + (win_rate - 0.5) * 4
    return round(min(0.98, max(0.02, 1 / (1 + math.exp(-x)))), 3)


def _calc_champion_prob(rank, num_teams, wins, losses):
    total    = wins + losses
    win_rate = wins / total if total > 0 else 0.5
    x        = (2 - rank) * 1.2 + (win_rate - 0.5) * 5
    return round(min(0.90, max(0.01, (1 / (1 + math.exp(-x))) / (num_teams * 0.3))), 3)


# ─── TEAM ROSTER ──────────────────────────────────────────────────────────────
@app.get("/api/team/{team_key}/roster")
async def get_roster(team_key: str):
    try:
        data = await yahoo_get(f"/team/{team_key}/roster/players")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error obteniendo roster: {str(e)}")

    players = []
    try:
        roster = data["fantasy_content"]["team"][1]["roster"]["0"]["players"]
        count  = roster["count"]
        for i in range(count):
            p         = roster[str(i)]["player"]
            info      = p[0]
            name_data = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            positions = next((x["display_position"] for x in info if isinstance(x, dict) and "display_position" in x), "")
            team_abbr = next((x["editorial_team_abbr"] for x in info if isinstance(x, dict) and "editorial_team_abbr" in x), "")
            status    = next((x.get("status", "A") for x in info if isinstance(x, dict) and "status" in x), "A")
            players.append({
                "name":     name_data.get("full", "Unknown"),
                "position": positions,
                "team":     team_abbr,
                "status":   status,
            })
    except (KeyError, TypeError) as e:
        raise HTTPException(500, f"Error parseando roster: {str(e)}")

    return {"players": players}


# ─── FREE AGENTS ──────────────────────────────────────────────────────────────
@app.get("/api/league/{league_key}/free-agents")
async def get_free_agents(league_key: str, position: str = "B", count: int = 25):
    try:
        data = await yahoo_get(
            f"/league/{league_key}/players;status=FA;position={position};sort=OR;count={count}/stats"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error obteniendo agentes libres: {str(e)}")

    agents = []
    try:
        players = data["fantasy_content"]["league"][1]["players"]
        for i in range(players.get("count", 0)):
            p         = players[str(i)]["player"]
            info      = p[0]
            stats     = p[1].get("player_stats", {}).get("stats", [])
            name_data = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            pkey      = next((x["player_key"] for x in info if isinstance(x, dict) and "player_key" in x), "")
            pos       = next((x["display_position"] for x in info if isinstance(x, dict) and "display_position" in x), "")
            team      = next((x["editorial_team_abbr"] for x in info if isinstance(x, dict) and "editorial_team_abbr" in x), "")
            pct       = next((x["percent_owned"] for x in info if isinstance(x, dict) and "percent_owned" in x), {})
            agents.append({
                "player_key":    pkey,
                "name":          name_data.get("full", "Unknown"),
                "position":      pos,
                "team":          team,
                "percent_owned": float(pct.get("value", 0)) if isinstance(pct, dict) else 0,
                "stats":         {s["stat"]["stat_id"]: s["stat"]["value"]
                                  for s in stats if isinstance(s.get("stat"), dict)},
            })
    except (KeyError, TypeError) as e:
        raise HTTPException(500, f"Error parseando agentes libres: {str(e)}")

    agents.sort(key=lambda x: x["percent_owned"], reverse=True)
    return {"free_agents": agents}


# ─── TRADE ANALYZER ───────────────────────────────────────────────────────────
@app.post("/api/trade/analyze")
async def analyze_trade(body: dict):
    give_keys    = body.get("give", [])
    receive_keys = body.get("receive", [])
    league_key   = body.get("league_key", "")

    if not give_keys or not receive_keys:
        raise HTTPException(400, "Provee jugadores para dar y recibir.")

    try:
        keys_str = ",".join(give_keys + receive_keys)
        data     = await yahoo_get(f"/league/{league_key}/players;player_keys={keys_str}/stats")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error analizando trade: {str(e)}")

    scores = {}
    try:
        players = data["fantasy_content"]["league"][1]["players"]
        for i in range(players.get("count", 0)):
            p         = players[str(i)]["player"]
            info      = p[0]
            pkey      = next((x["player_key"] for x in info if isinstance(x, dict) and "player_key" in x), "")
            name_data = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            stats     = p[1].get("player_stats", {}).get("stats", [])
            raw       = {s["stat"]["stat_id"]: float(s["stat"].get("value") or 0)
                         for s in stats if isinstance(s.get("stat"), dict)}
            scores[pkey] = {"name": name_data.get("full", "Unknown"), "score": _composite_score(raw)}
    except (KeyError, TypeError):
        pass

    give_score    = sum(scores.get(k, {}).get("score", 0) for k in give_keys)
    receive_score = sum(scores.get(k, {}).get("score", 0) for k in receive_keys)
    diff          = receive_score - give_score
    fairness      = "fair" if abs(diff) < give_score * 0.15 else ("favorable" if diff > 0 else "unfavorable")

    return {
        "give_players":    [scores.get(k, {"name": k, "score": 0}) for k in give_keys],
        "receive_players": [scores.get(k, {"name": k, "score": 0}) for k in receive_keys],
        "give_score":      round(give_score, 1),
        "receive_score":   round(receive_score, 1),
        "difference":      round(diff, 1),
        "fairness":        fairness,
        "verdict":         _trade_verdict(diff, give_score, fairness),
    }


def _composite_score(stats):
    weights = {"12": 3.0, "13": 2.0, "16": 2.5, "42": 1.5, "32": 4.0, "36": 3.0}
    score   = sum(float(stats.get(k, 0)) * w for k, w in weights.items())
    era     = float(stats.get("26", 4.0) or 4.0)
    whip    = float(stats.get("27", 1.25) or 1.25)
    score  -= (era - 4.0) * 8
    score  -= (whip - 1.25) * 15
    return max(0.0, score)


def _trade_verdict(diff, give_score, fairness):
    if fairness == "fair":
        return "Trade equilibrado. Acepta si el jugador que recibes llena una necesidad específica."
    elif fairness == "favorable":
        pct = round((diff / give_score) * 100) if give_score > 0 else 0
        return f"Trade favorable para ti (+{pct}% de valor). Recomendamos ACEPTAR."
    else:
        pct = round((-diff / give_score) * 100) if give_score > 0 else 0
        return f"Trade desfavorable ({pct}% menos valor). Considera renegociar o rechazar."


# ─── TEAM ANALYSIS ────────────────────────────────────────────────────────────
@app.get("/api/league/{league_key}/team/{team_key}/analysis")
async def analyze_team(league_key: str, team_key: str):
    standings_data = await get_standings(league_key)
    standings      = standings_data["standings"]
    num_teams      = len(standings)
    team           = next((t for t in standings if t["team_key"] == team_key), None)

    if not team:
        raise HTTPException(404, "Equipo no encontrado.")

    rank       = team["rank"]
    weaknesses = []
    recs       = []

    if rank > num_teams * 0.5:
        weaknesses.append("Batting average — por debajo del promedio de la liga")
        recs.append({"type": "add", "priority": "high",
                     "action": "Busca bateadores con AVG > .280 en agentes libres", "position": "OF/1B"})
    if rank > 3:
        weaknesses.append("Stolen bases — categoría frecuentemente descuidada")
        recs.append({"type": "add", "priority": "high",
                     "action": "Prioriza SS/OF velocistas en el waiver wire", "position": "SS/2B/OF"})
    if rank > num_teams * 0.6:
        weaknesses.append("Pitcheo — ERA y WHIP necesitan refuerzo")
        recs.append({"type": "add", "priority": "medium",
                     "action": "Agrega un SP de calidad disponible en agentes libres", "position": "SP"})

    return {
        "team_name":       team["name"],
        "rank":            rank,
        "num_teams":       num_teams,
        "weaknesses":      weaknesses,
        "recommendations": recs,
        "playoff_prob":    team["playoff_prob"],
        "champion_prob":   team["champion_prob"],
    }
