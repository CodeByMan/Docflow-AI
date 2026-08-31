def test_metrics_static_route_is_not_consumed_by_uuid_route(client):
    response = client.get("/documents/metrics/summary")

    assert response.status_code == 200
    assert response.json()["message"] == "Document metrics fetched"
    assert set(response.json()["data"]) == {
        "total",
        "uploaded",
        "queued",
        "processing",
        "completed",
        "failed",
    }


def test_listing_schema(client):
    response = client.get("/documents?limit=10")
    assert response.status_code == 200
    assert set(response.json()["data"]) == {"items", "count"}
