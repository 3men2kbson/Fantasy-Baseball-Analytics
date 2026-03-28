"""
Yahoo Fantasy Baseball Analytics — FastAPI Backend
Handles OAuth 2.0, API calls, and stats analysis
"""

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import httpx
import os
import json
import math
import time
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Fantasy Baseball Analytics API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

YAHOO_CLIENT_ID     = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI  = os.getenv("YAHOO_REDIRECT_URI", "http://localhost:8000/auth/callback")
YAHOO_BASE_URL      = "https://fantasysports.yahooapis.com/fantasy/v2"
YAHOO_AUTH_URL      = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL     = "https://api.login.yahoo.com/oauth2/get_token"

# In-memory token store (use Redis/DB in production)
TOKEN_STORE: dict = {}

# ─── AUTH ROUTES ─────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login():
    """Step 1: Redirect user to Yahoo OAuth consent page."""
    if not YAHOO_CLIENT_ID:
        raise HTTPException(400, "YAHOO_CLIENT_ID not configured. Check your .env file.")

    params = {
        "client_id":     YAHOO_CLIENT_ID,
        "redirect_uri":  YAHOO_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid fspt-r",   # fspt-r = Fantasy Sports read
        "nonce":         str(int(time.time())),
    }
    url = f"{YAHOO_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


#@app.get("/auth/callback")
#async def auth_callback(code: str, state: str = None):
#    """Step 2: Exchange code for tokens."""
#    import base64

#    credentials = base64.b64encode(
#        f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
#    ).decode()

#    async with httpx.AsyncClient() as client:
#        resp = await client.post(
#            YAHOO_TOKEN_URL,
#            headers={
#                "Authorization": f"Basic {credentials}",
#                "Content-Type": "application/x-www-form-urlencoded",
#            },
#            data={
#                "grant_type":   "authorization_code",
#                "code":         code,
#                "redirect_uri": YAHOO_REDIRECT_URI,
#            },
#        )

#    if resp.status_code != 200:
#        raise HTTPException(400, f"Token exchange failed: {resp.text}")

#    tokens = resp.json()
#    TOKEN_STORE["access_token"]  = tokens["access_token"]
#    TOKEN_STORE["refresh_token"] = tokens.get("refresh_token", "")
#    TOKEN_STORE["expires_at"]    = time.time() + tokens.get("expires_in", 3600)

#    # Redirect to frontend after successful auth
#    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
#    return RedirectResponse(f"{FRONTEND_URL}?auth=success")
    
#    #return RedirectResponse("http://localhost:5173?auth=success")

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
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": YAHOO_REDIRECT_URI,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(400, f"Error: {resp.text}")

    tokens = resp.json()
    TOKEN_STORE["access_token"]  = tokens["access_token"]
    TOKEN_STORE["refresh_token"] = tokens.get("refresh_token", "")
    TOKEN_STORE["expires_at"]    = time.time() + tokens.get("expires_in", 3600)

    # Devuelve HTML que cierra la ventana y notifica al frontend
    return Response(
        content="""<!DOCTYPE html>
<html>
<head><title>Autenticado</title></head>
<body>
<script>
  if (window.opener) {
    window.opener.postMessage('yahoo_auth_success', '*');
    window.close();
  } else {
    window.location.href = 'https://3men2kbson.github.io/Fantasy-Baseball-Analytics/';
  }
</script>
<p>Autenticado correctamente. Cerrando...</p>
</body>
</html>""",
        media_type="text/html"
    )


@app.get("/auth/status")
async def auth_status():
    """Check if user is authenticated."""
    if not TOKEN_STORE.get("access_token"):
        return {"authenticated": False}

    # Auto-refresh if near expiry
    if time.time() >= TOKEN_STORE.get("expires_at", 0) - 60:
        await _refresh_token()

    return {
        "authenticated": True,
        "expires_in": max(0, int(TOKEN_STORE.get("expires_at", 0) - time.time())),
    }


async def _refresh_token():
    """Refresh Yahoo access token automatically."""
    import base64
    credentials = base64.b64encode(
        f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            YAHOO_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
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


# ─── YAHOO API HELPER ────────────────────────────────────────────────────────

async def yahoo_get(path: str) -> dict:
    """Make authenticated GET request to Yahoo Fantasy API."""
    if not TOKEN_STORE.get("access_token"):
        raise HTTPException(401, "Not authenticated. Visit /auth/login first.")

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
        raise HTTPException(401, "Token expired, please retry.")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Yahoo API error: {resp.text[:300]}")

    return resp.json()


# ─── LEAGUES ─────────────────────────────────────────────────────────────────

@app.get("/api/leagues")
async def get_leagues():
    """Get all baseball leagues the user is in."""
    data = await yahoo_get("/users;use_login=1/games;game_codes=mlb/leagues")
    leagues = []

    try:
        users = data["fantasy_content"]["users"]
        user  = users["0"]["user"]
        games = user[1]["games"]

        for i in range(games["count"]):
            game = games[str(i)]["game"]
            game_leagues = game[1].get("leagues", {})
            for j in range(game_leagues.get("count", 0)):
                lg = game_leagues[str(j)]["league"][0]
                leagues.append({
                    "league_key":  lg["league_key"],
                    "league_id":   lg["league_id"],
                    "name":        lg["name"],
                    "season":      lg["season"],
                    "num_teams":   lg["num_teams"],
                    "current_week":lg.get("current_week"),
                    "scoring_type":lg.get("scoring_type"),
                })
    except (KeyError, TypeError):
        pass

    return {"leagues": leagues}


# ─── STANDINGS & TEAMS ───────────────────────────────────────────────────────

@app.get("/api/league/{league_key}/standings")
async def get_standings(league_key: str):
    """Get standings for a specific league with computed win probabilities."""
    data = await yahoo_get(f"/league/{league_key}/standings")

    standings = []
    try:
        league_data = data["fantasy_content"]["league"]
        teams_data  = league_data[1]["standings"][0]["teams"]
        num_teams   = teams_data["count"]

        for i in range(num_teams):
            team = teams_data[str(i)]["team"]
            info = team[0]
            standing = team[1]["team_standings"]

            name = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), "Unknown")
            team_key = next((x["team_key"] for x in info if isinstance(x, dict) and "team_key" in x), "")
            logo = next((x["team_logos"][0]["team_logo"]["url"]
                         for x in info if isinstance(x, dict) and "team_logos" in x), "")

            outcomes = standing.get("outcome_totals", {})
            wins   = int(outcomes.get("wins", 0))
            losses = int(outcomes.get("losses", 0))
            ties   = int(outcomes.get("ties", 0))
            rank   = int(standing.get("rank", i + 1))
            pts    = float(standing.get("points_for", 0))

            total_games = wins + losses + ties
            win_pct = (wins + ties * 0.5) / total_games if total_games > 0 else 0.0

            standings.append({
                "team_key":  team_key,
                "name":      name,
                "logo":      logo,
                "rank":      rank,
                "wins":      wins,
                "losses":    losses,
                "ties":      ties,
                "win_pct":   round(win_pct, 3),
                "points_for":pts,
                "playoff_prob":  _calc_playoff_prob(rank, num_teams, wins, losses),
                "champion_prob": _calc_champion_prob(rank, num_teams, wins, losses),
            })
    except (KeyError, TypeError, IndexError):
        pass

    return {"standings": sorted(standings, key=lambda x: x["rank"])}


def _calc_playoff_prob(rank: int, num_teams: int, wins: int, losses: int) -> float:
    """
    Simple Elo-based playoff probability.
    Assumes top 4 teams make playoffs in a 10-team league.
    """
    playoff_spots = max(2, num_teams // 2 - 1)
    total = wins + losses
    win_rate = wins / total if total > 0 else 0.5

    # Sigmoid centered on rank vs playoff cutoff
    x = (playoff_spots - rank) * 0.8 + (win_rate - 0.5) * 4
    prob = 1 / (1 + math.exp(-x))
    return round(min(0.98, max(0.02, prob)), 3)


def _calc_champion_prob(rank: int, num_teams: int, wins: int, losses: int) -> float:
    """Approximate championship probability based on rank."""
    total = wins + losses
    win_rate = wins / total if total > 0 else 0.5
    x = (2 - rank) * 1.2 + (win_rate - 0.5) * 5
    prob = 1 / (1 + math.exp(-x))
    return round(min(0.90, max(0.01, prob / (num_teams * 0.3))), 3)


# ─── TEAM ROSTER ─────────────────────────────────────────────────────────────

@app.get("/api/team/{team_key}/roster")
async def get_roster(team_key: str):
    """Get full roster with stats for a specific team."""
    data = await yahoo_get(
        f"/team/{team_key}/roster/players"
    )

    players = []
    try:
        roster = data["fantasy_content"]["team"][1]["roster"]["0"]["players"]
        count  = roster["count"]

        for i in range(count):
            p    = roster[str(i)]["player"]
            info = p[0]

            player_id   = next((x["player_id"] for x in info if isinstance(x, dict) and "player_id" in x), "")
            name_data   = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            full_name   = name_data.get("full", "Unknown")
            positions   = next((x["display_position"] for x in info if isinstance(x, dict) and "display_position" in x), "")
            team_abbr   = next((x["editorial_team_abbr"] for x in info if isinstance(x, dict) and "editorial_team_abbr" in x), "")
            status      = next((x.get("status", "A") for x in info if isinstance(x, dict) and "status" in x), "A")

            players.append({
                "player_id": player_id,
                "name":      full_name,
                "position":  positions,
                "team":      team_abbr,
                "status":    status,
            })
    except (KeyError, TypeError):
        pass

    return {"players": players}


# ─── PLAYER STATS ────────────────────────────────────────────────────────────

@app.get("/api/league/{league_key}/player-stats")
async def get_player_stats(league_key: str, player_keys: str):
    """
    Get stats for specific players.
    player_keys: comma-separated list of player keys
    """
    keys = player_keys[:10]  # Yahoo allows up to 25, but limit for safety
    keys_str = ",".join(keys)
    data = await yahoo_get(
        f"/league/{league_key}/players;player_keys={keys_str}/stats"
    )

    stats_list = []
    try:
        players = data["fantasy_content"]["league"][1]["players"]
        for i in range(players["count"]):
            p = players[str(i)]["player"]
            info  = p[0]
            stats = p[1].get("player_stats", {}).get("stats", [])

            name_data = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            stats_list.append({
                "name":  name_data.get("full", "Unknown"),
                "stats": {s["stat"]["stat_id"]: s["stat"]["value"] for s in stats if isinstance(s.get("stat"), dict)}
            })
    except (KeyError, TypeError):
        pass

    return {"player_stats": stats_list}


# ─── FREE AGENTS ─────────────────────────────────────────────────────────────

@app.get("/api/league/{league_key}/free-agents")
async def get_free_agents(league_key: str, position: str = "B", count: int = 25):
    """
    Get ranked free agents with fantasy scores.
    position: B=all batters, P=all pitchers, or specific (C,1B,2B,3B,SS,OF,SP,RP)
    """
    data = await yahoo_get(
        f"/league/{league_key}/players;status=FA;position={position};sort=OR;count={count}/stats"
    )

    agents = []
    try:
        players = data["fantasy_content"]["league"][1]["players"]
        for i in range(players.get("count", 0)):
            p = players[str(i)]["player"]
            info  = p[0]
            stats = p[1].get("player_stats", {}).get("stats", [])

            name_data = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            pkey  = next((x["player_key"] for x in info if isinstance(x, dict) and "player_key" in x), "")
            pos   = next((x["display_position"] for x in info if isinstance(x, dict) and "display_position" in x), "")
            team  = next((x["editorial_team_abbr"] for x in info if isinstance(x, dict) and "editorial_team_abbr" in x), "")
            pct   = next((x["percent_owned"] for x in info if isinstance(x, dict) and "percent_owned" in x), {})

            agents.append({
                "player_key":    pkey,
                "name":          name_data.get("full", "Unknown"),
                "position":      pos,
                "team":          team,
                "percent_owned": float(pct.get("value", 0)) if isinstance(pct, dict) else 0,
                "stats":         {s["stat"]["stat_id"]: s["stat"]["value"]
                                  for s in stats if isinstance(s.get("stat"), dict)},
            })
    except (KeyError, TypeError):
        pass

    # Rank by composite score (higher % owned = more valuable)
    agents.sort(key=lambda x: x["percent_owned"], reverse=True)
    return {"free_agents": agents}


# ─── TRADE ANALYZER ──────────────────────────────────────────────────────────

@app.post("/api/trade/analyze")
async def analyze_trade(body: dict):
    """
    Analyze a proposed trade.
    Body: {
      "give": ["player_key1", ...],
      "receive": ["player_key2", ...],
      "league_key": "..."
    }
    """
    give_keys    = body.get("give", [])
    receive_keys = body.get("receive", [])
    league_key   = body.get("league_key", "")

    if not give_keys or not receive_keys:
        raise HTTPException(400, "Must provide players to give and receive.")

    all_keys = give_keys + receive_keys
    keys_str = ",".join(all_keys)

    data = await yahoo_get(
        f"/league/{league_key}/players;player_keys={keys_str}/stats"
    )

    scores = {}
    try:
        players = data["fantasy_content"]["league"][1]["players"]
        for i in range(players.get("count", 0)):
            p = players[str(i)]["player"]
            info = p[0]
            pkey = next((x["player_key"] for x in info if isinstance(x, dict) and "player_key" in x), "")
            name_data = next((x["name"] for x in info if isinstance(x, dict) and "name" in x), {})
            stats = p[1].get("player_stats", {}).get("stats", [])
            raw   = {s["stat"]["stat_id"]: float(s["stat"].get("value") or 0)
                     for s in stats if isinstance(s.get("stat"), dict)}
            scores[pkey] = {
                "name":  name_data.get("full", "Unknown"),
                "score": _composite_score(raw),
                "stats": raw,
            }
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


def _composite_score(stats: dict) -> float:
    """
    Compute a composite fantasy score from raw stat IDs.
    Yahoo stat IDs for standard 5x5:
      Batting:  8=H, 12=HR, 13=RBI, 16=SB, 3=AVG
      Pitching: 28=IP, 32=W, 36=SV, 42=K, 26=ERA, 27=WHIP
    """
    weights = {
        "12": 3.0,   # HR
        "13": 2.0,   # RBI
        "16": 2.5,   # SB
        "42": 1.5,   # K (pitching)
        "32": 4.0,   # W
        "36": 3.0,   # SV
    }
    score = 0.0
    for stat_id, weight in weights.items():
        score += float(stats.get(stat_id, 0)) * weight

    # Penalize bad pitching stats
    era  = float(stats.get("26", 4.0) or 4.0)
    whip = float(stats.get("27", 1.25) or 1.25)
    if era > 0:
        score -= (era - 4.0) * 8
        score -= (whip - 1.25) * 15

    return max(0.0, score)


def _trade_verdict(diff: float, give_score: float, fairness: str) -> str:
    if fairness == "fair":
        return "Trade equilibrado. Acepta si el jugador que recibes llena una necesidad específica de tu equipo."
    elif fairness == "favorable":
        pct = round((diff / give_score) * 100) if give_score > 0 else 0
        return f"Trade favorable para ti (+{pct}% valor). Recomendamos ACEPTAR."
    else:
        pct = round((-diff / give_score) * 100) if give_score > 0 else 0
        return f"Trade desfavorable ({pct}% menos valor). Considera renegociar o rechazar."


# ─── TEAM WEAKNESSES ─────────────────────────────────────────────────────────

@app.get("/api/league/{league_key}/team/{team_key}/analysis")
async def analyze_team(league_key: str, team_key: str):
    """
    Analyze team weaknesses vs league average and return recommendations.
    """
    standings_data = await get_standings(league_key)
    standings = standings_data["standings"]
    num_teams = len(standings)

    # For demo: return weakness analysis based on standings rank
    team = next((t for t in standings if t["team_key"] == team_key), None)
    if not team:
        raise HTTPException(404, "Team not found in standings.")

    rank = team["rank"]
    weaknesses = []
    recommendations = []

    # Determine weakness areas based on rank (simplified without full stat breakdown)
    if rank > num_teams * 0.5:
        weaknesses.append("Batting average — por debajo del promedio de la liga")
        recommendations.append({
            "type": "add",
            "priority": "high",
            "action": "Busca bateadores con AVG > .280 en agentes libres",
            "position": "OF/1B",
        })

    if rank > 3:
        weaknesses.append("Stolen bases — categoría frecuentemente descuidada")
        recommendations.append({
            "type": "add",
            "priority": "high",
            "action": "Prioriza SS/OF velocistas en el waiver wire",
            "position": "SS/2B/OF",
        })

    if rank > num_teams * 0.6:
        weaknesses.append("Pitcheo — ERA y WHIP necesitan refuerzo")
        recommendations.append({
            "type": "add",
            "priority": "medium",
            "action": "Agrega un SP de calidad disponible en agentes libres",
            "position": "SP",
        })

    return {
        "team_name":       team["name"],
        "rank":            rank,
        "num_teams":       num_teams,
        "weaknesses":      weaknesses,
        "recommendations": recommendations,
        "playoff_prob":    team["playoff_prob"],
        "champion_prob":   team["champion_prob"],
    }


# ─── HEALTHCHECK ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status":  "online",
        "service": "Fantasy Baseball Analytics API",
        "docs":    "/docs",
        "auth":    "/auth/login",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
