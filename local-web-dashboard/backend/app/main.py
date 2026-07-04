from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="web-xray-dashboard backend")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "backend"}

    return app


app = create_app()
