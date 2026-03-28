# ⚾ Fantasy Baseball Analytics

Dashboard completo para análisis de Yahoo Fantasy Baseball.  
**Stack:** Python (FastAPI) + HTML/CSS/JS vanilla

---

## 🗂 Estructura del proyecto

```
fantasy-baseball/
├── backend/
│   ├── main.py            ← API Python (FastAPI)
│   ├── requirements.txt   ← Dependencias Python
│   ├── .env.example       ← Template de variables de entorno
│   └── .env               ← TUS credenciales (no commitear a git)
│
├── frontend/
│   └── index.html         ← Webapp completa (un solo archivo)
│
└── README.md
```

---

## 🔑 PASO 1 — Crear tu app en Yahoo Developer Console

> Solo necesitas hacer esto una vez.

1. Ve a **https://developer.yahoo.com/apps/create/**
2. Inicia sesión con tu cuenta de Yahoo (la misma que usas en Fantasy)
3. Llena el formulario:

   | Campo | Valor |
   |-------|-------|
   | **Application Name** | Fantasy Baseball Analytics |
   | **Description** | Personal fantasy analytics dashboard |
   | **Application Type** | Web Application |
   | **Homepage URL** | `http://localhost:5173` |
   | **Redirect URI(s)** | `http://localhost:8000/auth/callback` |

4. En **API Permissions**:
   - Busca **Fantasy Sports**
   - Selecciona ✅ **Read**

5. Haz click en **Create App**

6. Yahoo te mostrará tu **Client ID** y **Client Secret** — cópialos.

---

## 🐍 PASO 2 — Configurar el backend Python

```bash
# Entra a la carpeta del backend
cd fantasy-baseball/backend

# Instala dependencias
pip install -r requirements.txt

# Crea tu archivo .env
cp .env.example .env
```

Edita el archivo `.env` con tus credenciales:

```env
YAHOO_CLIENT_ID=dj0yJiI6XXXXXXXXXXXXXXXXXXXXXXXX
YAHOO_CLIENT_SECRET=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
YAHOO_REDIRECT_URI=http://localhost:8000/auth/callback
```

---

## 🚀 PASO 3 — Correr el servidor

```bash
# Desde la carpeta backend/
uvicorn main:app --reload --port 8000
```

Deberías ver:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

Verifica que funciona: http://localhost:8000/docs

---

## 🌐 PASO 4 — Abrir el frontend

Abre `frontend/index.html` directamente en tu navegador, o usa cualquier servidor local:

```bash
# Opción A: Python (más simple)
cd fantasy-baseball/frontend
python -m http.server 5173

# Opción B: VS Code Live Server
# Instala la extensión "Live Server" y haz click en "Go Live"

# Opción C: Node.js
npx serve frontend -p 5173
```

Luego abre: **http://localhost:5173**

---

## 🔐 PASO 5 — Autenticación Yahoo OAuth

1. En la webapp haz click en **"Conectar Yahoo"**
2. Te redirigirá a Yahoo para que apruebes el acceso
3. Yahoo te redirige de vuelta con `?auth=success`
4. ¡Listo! Ya puedes ver tus ligas

---

## 📡 Endpoints del API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/auth/login` | Inicia flujo OAuth |
| GET | `/auth/callback` | Callback de Yahoo (automático) |
| GET | `/auth/status` | Verifica si estás autenticado |
| GET | `/api/leagues` | Tus ligas de béisbol |
| GET | `/api/league/{key}/standings` | Standings + probabilidades |
| GET | `/api/team/{key}/roster` | Roster completo de un equipo |
| GET | `/api/league/{key}/free-agents` | Agentes libres por posición |
| POST | `/api/trade/analyze` | Analiza un trade |
| GET | `/api/league/{key}/team/{key}/analysis` | Debilidades y recomendaciones |

Documentación interactiva: http://localhost:8000/docs

---

## ❓ Preguntas frecuentes

**P: ¿Qué scope de Yahoo necesito?**  
R: `fspt-r` (Fantasy Sports Read). Se configura automáticamente en el flujo OAuth.

**P: El token expira, ¿qué pasa?**  
R: El backend hace refresh automático cuando queda menos de 60 segundos de vida.

**P: ¿Puedo hacer propuestas de trade desde aquí?**  
R: El analizador de trades evalúa el valor — para enviar la propuesta real necesitarías el scope `fspt-w` (write) y un endpoint adicional. Se puede agregar fácilmente.

**P: ¿Funciona con ligas de puntos y H2H?**  
R: Sí, Yahoo API devuelve ambos tipos. Las probabilidades se calculan con win% en H2H.

**P: ¿Puedo hacer deploy en producción?**  
R: Sí, cambia `YAHOO_REDIRECT_URI` en el `.env` a tu dominio real y actualiza la Callback URL en Yahoo Developer Console.

---

## 🔧 Tecnologías

- **Backend:** Python 3.10+, FastAPI, httpx, uvicorn
- **Frontend:** HTML5, CSS3 (variables, grid, flexbox), JavaScript ES2020
- **Auth:** Yahoo OAuth 2.0 (PKCE-compatible)
- **API:** Yahoo Fantasy Sports REST API v2
