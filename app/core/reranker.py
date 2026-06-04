from __future__ import annotations
import math
from typing import Any, Dict, List


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def proximity_decay(distance_km: float, half_life_km: float = 2.0) -> float:
    lam = math.log(2) / half_life_km
    return math.exp(-lam * max(0.0, distance_km))


def quality_boost(payload: dict) -> float:
    score = 0.0
    if payload.get("xirifyAssured"):
        score += 0.30
    if payload.get("topRated"):
        score += 0.20
    if payload.get("popular"):
        score += 0.10
    if payload.get("isnew"):
        score += 0.05
    rating = float(payload.get("overallRating") or 0)
    score += (rating / 5.0) * 0.15
    return min(score, 1.0)


def rrf_fuse(
    vector_results: List[Any],
    text_results: List[Dict],
    k: int = 60,
) -> Dict[str, Dict]:
    scores: Dict[str, Dict] = {}

    for rank, hit in enumerate(vector_results):
        payload = hit.payload or {}
        # Key on the Mongo _id (carried in payload) so vector + text hits for the
        # same entity collapse into one bucket and Mongo hydration works. The
        # Qdrant point id (hit.id) is a derived UUID and is NOT a Mongo id.
        item_id = str(payload.get("mongoId") or hit.id)
        scores[item_id] = {
            "vector_score": float(hit.score),
            "rrf_score": 1.0 / (k + rank + 1),
            "payload": payload,
        }

    for rank, hit in enumerate(text_results):
        item_id = str(hit.get("_id", ""))
        if not item_id:
            continue
        if item_id in scores:
            scores[item_id]["rrf_score"] += 1.0 / (k + rank + 1)
        else:
            scores[item_id] = {
                "vector_score": 0.0,
                "rrf_score": 1.0 / (k + rank + 1),
                "payload": hit,
            }

    return scores


def compute_final_scores(
    fused: Dict[str, Dict],
    consumer_lat: float,
    consumer_lng: float,
    weights: Dict[str, float] = None,
) -> List[Dict]:
    w = weights or {"vector": 0.4, "rrf": 0.3, "proximity": 0.2, "quality": 0.1}
    results = []

    for item_id, data in fused.items():
        payload = data["payload"]
        loc = payload.get("location") or {}
        dist_km = 0.0
        if loc.get("lat") and loc.get("lon"):
            dist_km = haversine(consumer_lat, consumer_lng, loc["lat"], loc["lon"])

        prox = proximity_decay(dist_km) if loc else 0.5
        qual = quality_boost(payload)

        final = (
            w["vector"] * data["vector_score"]
            + w["rrf"] * data["rrf_score"]
            + w["proximity"] * prox
            + w["quality"] * qual
        )
        results.append({
            "id": item_id,
            "final_score": final,
            "vector_score": data["vector_score"],
            "rrf_score": data["rrf_score"],
            "distance_km": round(dist_km, 2),
            "payload": payload,
        })

    return sorted(results, key=lambda x: x["final_score"], reverse=True)
