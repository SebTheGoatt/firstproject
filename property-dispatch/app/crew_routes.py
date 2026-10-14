"""Crew sign-in, profiles, portfolios, and the public "Meet the crew" pages.

    GET    /api/crew/roster              sign-in screen: who's on the crew (public)
    POST   /api/crew/login               crew member: their id + personal code
    POST   /api/crew/login/owner         owner: master code
    GET    /api/crew/me                  my profile + stats
    PUT    /api/crew/me                  edit my profile
    PUT    /api/crew/me/photo            set my profile photo
    PUT    /api/crew/me/code             change my personal code
    GET    /api/crew/me/portfolio        my work photos
    POST   /api/crew/me/portfolio        add a work photo
    DELETE /api/crew/me/portfolio/{id}   remove one of my photos
    GET    /api/crew/members             owner: everyone, including inactive
    POST   /api/crew/members             owner: add a crew member
    PATCH  /api/crew/members/{id}        owner: rename, reset code, deactivate
    GET    /api/team, /api/team/{slug}   public profiles + portfolios
    GET    /media/crew/{id}, /media/portfolio/{id}   photos
"""

import hmac
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .booking import local_now
from .config import Settings
from .crew_auth import OWNER, CrewIdentity, LoginThrottle, SessionSigner, check_code, hash_code, slugify, valid_code
from .media import MediaError, normalize_photo, parse_photo
from .models import CrewProfileUpdate, Service


class LoginBody(BaseModel):
    member_id: str
    code: str = Field(max_length=64)


class OwnerLoginBody(BaseModel):
    code: str = Field(max_length=256)


class PhotoBody(BaseModel):
    photo: str = Field(max_length=1_000_000)


class PortfolioBody(BaseModel):
    photo: str = Field(max_length=1_000_000)
    caption: str | None = Field(default=None, max_length=280)
    service: Service | None = None
    job_id: str | None = None


class ChangeCodeBody(BaseModel):
    current: str = Field(max_length=64)
    new: str = Field(max_length=64)


class NewMemberBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    code: str = Field(max_length=64)
    role_title: str | None = Field(default=None, max_length=60)


class MemberPatchBody(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    role_title: str | None = Field(default=None, max_length=60)
    code: str | None = Field(default=None, max_length=64)
    active: bool | None = None


def photo_url(m: dict) -> str | None:
    if not m.get("photo_updated_at"):
        return None
    v = str(m["photo_updated_at"]).replace(":", "").replace("-", "")[:15]
    return f"/media/crew/{m['id']}?v={v}"


def public_member(m: dict) -> dict:
    return {
        "id": m["id"], "slug": m["slug"], "display_name": m["display_name"], "role_title": m.get("role_title"),
        "bio": m.get("bio"), "years_experience": m.get("years_experience"),
        "specialties": m.get("specialties") or [], "service_branch": m.get("service_branch"),
        "accent_color": m.get("accent_color") or "#2f7d4f", "photo_url": photo_url(m),
    }


def portfolio_view(item: dict) -> dict:
    return {**item, "photo_url": f"/media/portfolio/{item['id']}"}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def register_crew_routes(app: FastAPI, settings: Settings):
    """Adds the routes and returns the `crew_auth` dependency for other crew-only endpoints."""
    signer = SessionSigner(settings.crew_access_token)
    throttle = LoginThrottle()

    def repo(request: Request):
        return request.app.state.repo

    def crew_auth(request: Request, x_crew_token: str | None = Header(default=None)) -> CrewIdentity:
        if not x_crew_token:
            raise HTTPException(status_code=401, detail="Please sign in.")
        # The owner's master code still works directly (older crew-app versions, scripts).
        if hmac.compare_digest(x_crew_token.encode(), settings.crew_access_token.encode()):
            return CrewIdentity(member_id=None, is_owner=True)
        sub = signer.read(x_crew_token)
        if sub == OWNER:
            return CrewIdentity(member_id=None, is_owner=True)
        if sub:
            m = request.app.state.repo.get_crew(sub)
            if m and m["active"]:
                return CrewIdentity(member_id=sub, is_owner=False)
        raise HTTPException(status_code=401, detail="Your sign-in has expired. Please sign in again.")

    def member_only(who: CrewIdentity = Depends(crew_auth)) -> CrewIdentity:
        if who.member_id is None:
            raise HTTPException(status_code=403, detail="Sign in as a crew member to use your profile.")
        return who

    def owner_only(who: CrewIdentity = Depends(crew_auth)) -> CrewIdentity:
        if not who.is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can manage the crew.")
        return who

    def week_start() -> datetime:
        now = local_now(settings)
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)

    # ---------- Sign-in ----------
    @app.get("/api/crew/roster")
    def roster(r=Depends(repo)):
        return [{k: public_member(m)[k] for k in ("id", "display_name", "role_title", "photo_url", "accent_color")}
                for m in r.list_crew()]

    @app.post("/api/crew/login")
    def login(body: LoginBody, request: Request, r=Depends(repo)):
        ip = _client_ip(request)
        if throttle.blocked(ip):
            raise HTTPException(status_code=429, detail="Too many tries. Wait 15 minutes and try again.")
        m = r.get_crew(body.member_id, with_secret=True)
        if not m or not m["active"] or not check_code(body.code, m["passcode_hash"]):
            throttle.fail(ip)
            raise HTTPException(status_code=401, detail="That code didn't match. Try again.")
        throttle.reset(ip)
        return {"token": signer.issue(m["id"]), "member": public_member(m), "is_owner": False}

    @app.post("/api/crew/login/owner")
    def owner_login(body: OwnerLoginBody, request: Request):
        ip = _client_ip(request)
        if throttle.blocked(ip):
            raise HTTPException(status_code=429, detail="Too many tries. Wait 15 minutes and try again.")
        if not hmac.compare_digest(body.code.encode(), settings.crew_access_token.encode()):
            throttle.fail(ip)
            raise HTTPException(status_code=401, detail="That's not the owner code.")
        throttle.reset(ip)
        return {"token": signer.issue(OWNER), "member": None, "is_owner": True}

    # ---------- My profile ----------
    @app.get("/api/crew/me")
    def me(who: CrewIdentity = Depends(crew_auth), r=Depends(repo)):
        if who.member_id is None:
            return {"is_owner": True, "member": None, "stats": None}
        m = r.get_crew(who.member_id)
        return {"is_owner": False, "member": public_member(m), "stats": r.crew_stats(who.member_id, week_start())}

    @app.put("/api/crew/me")
    def update_me(body: CrewProfileUpdate, who: CrewIdentity = Depends(member_only), r=Depends(repo)):
        fields = body.model_dump(exclude_unset=True)
        if "display_name" in fields and not fields["display_name"]:
            raise HTTPException(status_code=422, detail="Your name can't be empty.")
        m = r.update_crew(who.member_id, fields) if fields else r.get_crew(who.member_id)
        return public_member(m)

    @app.put("/api/crew/me/photo")
    def set_photo(body: PhotoBody, who: CrewIdentity = Depends(member_only), r=Depends(repo)):
        try:
            photo = normalize_photo(body.photo)
        except MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        m = r.update_crew(who.member_id, {"photo": photo, "photo_updated_at": datetime.now().astimezone().isoformat()})
        return public_member(m)

    @app.put("/api/crew/me/code")
    def change_code(body: ChangeCodeBody, request: Request, who: CrewIdentity = Depends(member_only), r=Depends(repo)):
        ip = _client_ip(request)
        if throttle.blocked(ip):
            raise HTTPException(status_code=429, detail="Too many tries. Wait 15 minutes and try again.")
        m = r.get_crew(who.member_id, with_secret=True)
        if not check_code(body.current, m["passcode_hash"]):
            throttle.fail(ip)
            raise HTTPException(status_code=401, detail="Your current code didn't match.")
        if not valid_code(body.new):
            raise HTTPException(status_code=422, detail="Pick a code with 4 to 32 characters.")
        r.update_crew(who.member_id, {"passcode_hash": hash_code(body.new)})
        return {"ok": True}

    # ---------- My portfolio ----------
    @app.get("/api/crew/me/portfolio")
    def my_portfolio(who: CrewIdentity = Depends(member_only), r=Depends(repo)):
        return [portfolio_view(i) for i in r.list_portfolio(who.member_id)]

    @app.post("/api/crew/me/portfolio", status_code=201)
    def add_portfolio(body: PortfolioBody, who: CrewIdentity = Depends(member_only), r=Depends(repo)):
        try:
            photo = normalize_photo(body.photo)
        except MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        caption = (body.caption or "").strip() or None
        item = r.add_portfolio(who.member_id, photo=photo, caption=caption,
                               service=body.service.value if body.service else None, job_id=body.job_id)
        return portfolio_view(item)

    @app.delete("/api/crew/me/portfolio/{item_id}", status_code=204)
    def delete_portfolio(item_id: str, who: CrewIdentity = Depends(member_only), r=Depends(repo)):
        if not r.delete_portfolio(item_id, who.member_id):
            raise HTTPException(status_code=404, detail="Photo not found")
        return Response(status_code=204)

    # ---------- Owner: manage the crew ----------
    @app.get("/api/crew/members", dependencies=[Depends(owner_only)])
    def all_members(r=Depends(repo)):
        return [{**public_member(m), "active": m["active"]} for m in r.list_crew(include_inactive=True)]

    @app.post("/api/crew/members", status_code=201, dependencies=[Depends(owner_only)])
    def add_member(body: NewMemberBody, r=Depends(repo)):
        if not valid_code(body.code):
            raise HTTPException(status_code=422, detail="Personal codes need 4 to 32 characters.")
        taken = {m["slug"] for m in r.list_crew(include_inactive=True)}
        base = slugify(body.display_name)
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        m = r.create_crew({"slug": slug, "display_name": body.display_name.strip(),
                           "role_title": (body.role_title or "").strip() or None,
                           "passcode_hash": hash_code(body.code)})
        return {**public_member(m), "active": True}

    @app.patch("/api/crew/members/{member_id}", dependencies=[Depends(owner_only)])
    def patch_member(member_id: str, body: MemberPatchBody, r=Depends(repo)):
        fields = body.model_dump(exclude_unset=True, exclude={"code"})
        if body.code is not None:
            if not valid_code(body.code):
                raise HTTPException(status_code=422, detail="Personal codes need 4 to 32 characters.")
            fields["passcode_hash"] = hash_code(body.code)
        m = r.update_crew(member_id, fields) if fields else r.get_crew(member_id)
        if m is None:
            raise HTTPException(status_code=404, detail="Crew member not found")
        return {**public_member(m), "active": m["active"]}

    # ---------- Public profiles ----------
    @app.get("/api/team")
    def team(r=Depends(repo)):
        return [public_member(m) for m in r.list_crew()]

    @app.get("/api/team/{slug}")
    def team_member(slug: str, r=Depends(repo)):
        m = r.get_crew_by_slug(slug)
        if m is None:
            raise HTTPException(status_code=404, detail="We couldn't find that crew member.")
        stats = r.crew_stats(m["id"], week_start())
        return {**public_member(m), "jobs_total": stats["jobs_total"],
                "portfolio": [portfolio_view(i) for i in r.list_portfolio(m["id"], limit=48)]}

    def image_response(data_url: str | None) -> Response:
        if not data_url:
            raise HTTPException(status_code=404, detail="No photo")
        try:
            content_type, raw = parse_photo(data_url)
        except MediaError:
            raise HTTPException(status_code=404, detail="No photo")
        return Response(raw, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/media/crew/{member_id}", include_in_schema=False)
    def crew_photo(member_id: str, r=Depends(repo)):
        return image_response(r.crew_photo(member_id))

    @app.get("/media/portfolio/{item_id}", include_in_schema=False)
    def portfolio_photo(item_id: str, r=Depends(repo)):
        return image_response(r.portfolio_photo(item_id))

    return crew_auth
