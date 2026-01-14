"""GeoQuiz MCP server for VWorld satellite-based map quizzes with Streamable HTTP SSE support."""

import json
import os
from typing import Dict, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from geopy.geocoders import Nominatim
import asyncio


VWORLD_API_KEY = os.getenv("VWORLD_API_KEY", "DEMO_KEY")
DEFAULT_IMAGE_SIZE = "1024,1024"


def _build_vworld_static_url(
    lon: float, lat: float, zoom: int, basemap: str, size: str = DEFAULT_IMAGE_SIZE
) -> str:
    """Constructs a VWorld static image URL."""
    return (
        "https://api.vworld.kr/req/image?service=image"
        f"&request=getmap&key={VWORLD_API_KEY}"
        f"&center={lon},{lat}&zoom={zoom}&basemap={basemap}&format=png"
        f"&size={size}"
    )


QuizRecord = Dict[str, object]


class QuizStore:
    """In-memory quiz session storage."""

    def __init__(self) -> None:
        self._store: Dict[str, QuizRecord] = {}

    def create(self, location_data: Dict) -> QuizRecord:
        """클라이언트가 제공한 위치 데이터로 퀴즈 생성"""
        quiz_id = f"quiz-{len(self._store) + 1}"
        record: QuizRecord = {
            "quiz_id": quiz_id,
            "candidate": location_data,
        }
        self._store[quiz_id] = record
        return record

    def get(self, quiz_id: str) -> QuizRecord:
        if quiz_id not in self._store:
            raise ValueError("Unknown quiz_id; request a new quiz first.")
        return self._store[quiz_id]


mcp = FastAPI(title="GeoQuiz MCP Server (VWorld) - Streamable HTTP")
store = QuizStore()


@mcp.post("/tools/create_map_quiz/stream")
async def create_map_quiz_stream(
    condition: str,
    quiz_type: str,
    lat: float,
    lon: float,
    zoom: int = 12,
    tags: list = None,
) -> StreamingResponse:
    """클라이언트 LLM이 선택한 위치로 지도 퀴즈를 생성합니다 (SSE 스트리밍 방식).

    Args:
        condition: 사용자가 요청한 문제의 조건
            - 문제 조건으로 특정 지역이 지정되면 정답 유형을 그에 속한 하위 행정구역이나 자연지형으로 할 것    
        quiz_type: 세부 정답 유형 (정답 자체가 아닌, 정답의 종류)
            - 외국 국가명/대도시·광역행정구역 또는 국내 광역시·도/시·군·구/읍·면·동 등 정답 행정구역의 단위
            - 산/강/섬/바다/호수/사막/빙하 등 정답 자연지형의 종류
            
        lat: 위도 (문제 유형이 행정구역일 경우 청사 위치를 기준으로 선정)
        lon: 경도 (문제 유형이 행정구역일 경우 청사 위치를 기준으로 선정)
        zoom: 지도 확대 레벨 (기준 절대 준수)
            - 한반도 내: quiz_type에 따라 다음 기준을 적용
                광역시·도: 11-12
                시·군·구: 13-14
                읍·면·동: 15-16
                자연지형은 크기가 작을수록 값을 높임
            - 외국: 8(대상이 한반도보다 클 경우 7), 외국의 경우 7-8 이외의 숫자는 에러 발생
        tags: 태그 목록 (선택)
    
    Returns:
        퀴즈 ID와 지도 URL이 포함된 메시지 (SSE 스트리밍)
        (반드시 message 문구를 그대로 사용자에게 보여주고, 마크다운 링크를 클릭 가능한 상태로 제공하시오. 
        이후 이미지 중점을 기준으로 출제했다는 것을 설명하고, '어떤 (국가/행정구역명, 시도/시군구/읍면동, 산/강/섬/바다 등)인가요?' 처럼 세부 정답 유형을 설명하시오.)
    """
    
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # 위치 검증 스트림
            yield f"data: {json.dumps({'status': 'validating', 'message': '위치 검증 중...', 'stage': 1})}\n\n"
            await asyncio.sleep(0.1)
            
            geolocator = Nominatim(user_agent="geoquiz_validator")
            location = geolocator.reverse(f"{lat}, {lon}", language="ko")
            
            if location is None:
                yield f"data: {json.dumps({'status': 'error', 'message': '유효하지 않은 좌표입니다.'})}\n\n"
                return
            
            address = location.address
            yield f"data: {json.dumps({'status': 'validated', 'message': f'✅ 검증 성공: {address}', 'stage': 2})}\n\n"
            await asyncio.sleep(0.1)
            
            # 퀴즈 생성 스트림
            yield f"data: {json.dumps({'status': 'creating', 'message': '퀴즈 생성 중...', 'stage': 3})}\n\n"
            await asyncio.sleep(0.1)
            
            location_data = {
                "condition": condition,
                "address": address,
                "quiz_type": quiz_type,
                "lat": lat,
                "lon": lon,
                "zoom": zoom,
                "tags": tags or [],
            }
            
            record = store.create(location_data)
            quiz_id_val = record['quiz_id']
            created_data = {'status': 'created', 'message': f'퀴즈 생성됨: {quiz_id_val}', 'quiz_id': quiz_id_val, 'stage': 4}
            yield f"data: {json.dumps(created_data)}\n\n"
            await asyncio.sleep(0.1)
            
            # URL 생성 스트림
            vworld_url = _build_vworld_static_url(
                lon, lat, zoom, basemap="PHOTO", size=DEFAULT_IMAGE_SIZE
            )
            yield f"data: {json.dumps({'status': 'url_ready', 'message': '지도 URL 생성됨', 'stage': 5})}\n\n"
            await asyncio.sleep(0.1)
            
            # 최종 결과 스트림
            result_message = (
                f"🗺️ 퀴즈가 생성되었습니다! (ID: {record['quiz_id']})\n"
                f"📍 [지도 열람]({vworld_url})\n\n"
                f"이미지 한가운데 지점은 어느 {quiz_type}일까요?"
            )
            
            yield f"data: {json.dumps({'status': 'complete', 'message': result_message, 'quiz_id': record['quiz_id'], 'vworld_url': vworld_url, 'stage': 6})}\n\n"
            
        except Exception as e:
            error_msg = f"❌ 오류 발생: {str(e)}"
            yield f"data: {json.dumps({'status': 'error', 'message': error_msg})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@mcp.get("/tools/request_hint/stream/{quiz_id}")
async def request_hint_stream(quiz_id: str) -> StreamingResponse:
    """quiz_id의 힌트를 제공합니다 (SSE 스트리밍 방식).
    힌트에 정답과 동일하거나 유사한 단어가 포함될 경우 다른 힌트를 제시하시오.
    """
    
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield f"data: {json.dumps({'status': 'loading', 'message': '힌트 준비 중...', 'stage': 1})}\n\n"
            await asyncio.sleep(0.1)
            
            record = store.get(quiz_id)
            candidate = record["candidate"]
            quiz_type = candidate.get("quiz_type", "미지정")
            address = candidate["address"]
            
            yield f"data: {json.dumps({'status': 'complete', 'quiz_id': quiz_id, 'quiz_type': quiz_type, 'address': address, 'stage': 2})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@mcp.get("/tools/request_answer/stream/{quiz_id}")
async def request_answer_stream(quiz_id: str) -> StreamingResponse:
    """정답(하이브리드 지도 링크 및 해설)을 제공합니다 (SSE 스트리밍 방식)."""
    
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield f"data: {json.dumps({'status': 'loading', 'message': '정답 준비 중...', 'stage': 1})}\n\n"
            await asyncio.sleep(0.1)
            
            record = store.get(quiz_id)
            candidate = record["candidate"]
            lon, lat = candidate["lon"], candidate["lat"]
            zoom = candidate["zoom"]
            condition = candidate["condition"]
            address = candidate["address"]
            quiz_type = candidate.get("quiz_type", "미지정")
            
            maps_url = f'https://www.google.com/maps/@{lat},{lon},{zoom}z'
            result_data = {'status': 'complete', 'quiz_id': quiz_id, 'quiz_type': quiz_type, 'center': {'lon': lon, 'lat': lat}, 'google_maps_url': maps_url, 'condition': condition, 'address': address, 'stage': 2}
            yield f"data: {json.dumps(result_data)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp, host="0.0.0.0", port=8000)