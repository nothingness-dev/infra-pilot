"""Fresh synthetic PaaS-shaped payloads; never inferred live measurements."""


def mock_payload(capability, name, params, mode):
    if mode == "missing":
        return None
    if mode == "invalid_response":
        return "invalid mock response"
    empty = mode == "empty"
    if capability == "projects":
        return {"projects": [] if empty else [
            {"_id": "mock-project-001", "project_id": "infrapilot-api", "type": "python", "status": "running"},
            {"_id": "mock-project-002", "project_id": "infrapilot-web", "type": "next", "status": "running"},
        ]}
    if capability == "service":
        return {"project": {} if empty else {
            "_id": "mock-project-001", "project_id": name, "type": "python",
            "status": "mock-running", "isDeployed": True,
        }}
    if capability == "logs":
        return [] if empty else [{
            "type": "mock-stdout", "datetime": "2026-01-01T00:00:00Z",
            "message": "Synthetic application started",
        }]
    if capability == "metrics":
        return {
            "cpuUsage": [] if empty else [{"applet": "mock-applet", "value": ["0.25"]}],
            "memoryUsage": [] if empty else [{"applet": "mock-applet", "value": ["104857600"]}],
            "disksUsage": [] if empty else [{
                "name": "mock-disk", "size": "1073741824", "usage": "104857600",
                "reportedAt": "2026-01-01T00:00:00Z",
            }],
        }
    if capability == "releases":
        releases = [] if empty else [{
            "_id": f"mock-release-{index}", "state": "mock-ready",
            "createdAt": "2026-01-01T00:00:00Z", "finishedAt": None,
            "tag": f"mock-v{index}",
        } for index in (2, 1)]
        page, count = params["page"], params["count"]
        return {
            "releases": releases[(page - 1) * count:page * count], "total": len(releases),
            "currentRelease": None if empty else "mock-release-2",
            "readyReleasesCount": len(releases),
        }
    raise ValueError("Unknown mock capability.")
