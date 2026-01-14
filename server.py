"""GeoQuiz MCP server for VWorld satellite-based map quizzes with Streamable HTTP SSE support."""

import json
import os
from typing import Dict, AsyncGenerator

from fastmcp import FastMCP
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


mcp = FastMCP("GeoQuiz MCP Server (VWorld)")
app = mcp
store = QuizStore()


@mcp.tool(description="Create a map-based geography quiz using VWorld satellite imagery. Generates a quiz with specified location and type.")
async def create_map_quiz(
    condition: str,
    iskorea: bool,
    quiz_type: str,
    lat: float,
    lon: float,
    zoom: int = 12,
    tags: list = None,
) -> str:
    """클라이언트 LLM이 선택한 위치로 지도 퀴즈를 생성합니다 (SSE 스트리밍 방식).

    Args:
        condition: 사용자가 요청한 문제의 조건
            - 문제 조건으로 특정 지역이 지정되면 정답 유형을 그에 속한 하위 행정구역이나 자연지형으로 할 것 
        iskorea: 문제 조건이 한반도 내 위치 여부 (True/False)   
        quiz_type: 세부 정답 유형 (정답 자체가 아닌, 정답의 종류)
            - 외국 국가명/대도시·광역행정구역 등 정답 행정구역의 단위
            - 국내 광역시·도/시·군·구/읍·면·동 등 정답 행정구역의 단위
            - 산/강/섬/바다/호수/사막/빙하 등 정답 자연지형의 종류
            
        lat: 위도 (문제 유형이 행정구역일 경우 청사 위치를 기준으로 선정)
        lon: 경도 (문제 유형이 행정구역일 경우 청사 위치를 기준으로 선정)
        zoom: 지도 확대 레벨 (기준 절대 준수)
            - iskorea = True: zoom = (quiz_type에 따라 다음 기준을 적용)
                도: 10-11
                특별광역시: 12
                시·군: 13
                구: 14
                읍·면:15
                동:16
                자연지형은 크기가 작을수록 값을 높임
            - iskorea = False: zoom = 8(대상이 한반도보다 클 경우 7)
        tags: 태그 목록 (선택)
    
    Returns:
        퀴즈 ID와 지도 URL이 포함된 메시지 (SSE 스트리밍)
        (반드시 message 문구를 그대로 사용자에게 보여주고, 마크다운 링크를 클릭 가능한 상태로 제공하시오. 
        이후 이미지 중점을 기준으로 출제했다는 것을 설명하고, '어떤 (국가/행정구역명, 시도/시군구/읍면동, 산/강/섬/바다 등)인가요?' 처럼 세부 정답 유형을 설명하시오.)
    """
    try:
        # 위치 검증

        if iskorea is False and not (7 <= zoom <= 8):
            raise ValueError("외국 위치의 경우 zoom 값은 7 또는 8이어야 합니다.")
        elif iskorea is True and not (10 <= zoom <= 16):
            raise ValueError("한반도 내 위치의 경우 zoom 값은 10에서 16 사이여야 합니다.")


        geolocator = Nominatim(user_agent="geoquiz_validator")
        location = geolocator.reverse((lat, lon), language="ko")
        
        if location is None:
            raise ValueError("유효하지 않은 좌표입니다. 다시 시도해주세요.")
        
        address = location.address
        
        # 퀴즈 생성
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
        
        # URL 생성
        vworld_url = _build_vworld_static_url(
            lon, lat, zoom, basemap="PHOTO", size=DEFAULT_IMAGE_SIZE
        )
        
        message = (
            "(반드시 아래 문구를 그대로 사용자에게 보여주고, 마크다운 링크를 클릭 가능한 상태로 제공하시오. "
            "이후 이미지 중점을 기준으로 출제했다는 것을 설명하고, '어떤 (국가/행정구역명, 시도/시군구/읍면동, 산/강/섬/바다 등)인가요?' 처럼 세부 정답 유형을 설명하시오.)"
            f"🗺️ 퀴즈가 생성되었습니다! (ID: {record['quiz_id']})\n"
            f"📍 [지도 열람]({vworld_url})\n\n"
            f"이미지 한가운데 지점은 어느 {quiz_type}일까요?"
        )
        return message
        
    except Exception as e:
        error_msg = f"❌ 오류 발생: {str(e)}"
        raise ValueError(error_msg)


@mcp.tool(description="Request hints for a specific quiz by quiz_id. Provides clues without revealing the exact answer.")
def request_hint(quiz_id: str) -> Dict[str, str]:
    """quiz_id의 힌트를 제공합니다 (SSE 스트리밍 방식).
    힌트에 정답과 동일하거나 유사한 단어가 포함될 경우 다른 힌트를 제시하시오.
    """
    try:
        record = store.get(quiz_id)
        candidate = record["candidate"]
        quiz_type = candidate.get("quiz_type", "미지정")
        lon, lat = candidate["lon"], candidate["lat"]
        condition = candidate["condition"]
        
        hint: Dict[str, str] = {
            "quiz_id": quiz_id,
            "quiz_type": quiz_type,
            "center": {"lon": lon, "lat": lat},
            "condition": condition,
        }
        return hint
    except Exception as e:
        raise ValueError(f"오류 발생: {str(e)}")

@mcp.tool(description="Get the answer for a specific quiz by quiz_id. Returns complete answer with map link and explanation.")
def request_answer(quiz_id: str) -> Dict[str, object]:
    """정답(하이브리드 지도 링크 및 해설)을 제공합니다 (SSE 스트리밍 방식)."""
    try:
        record = store.get(quiz_id)
        candidate = record["candidate"]
        lon, lat = candidate["lon"], candidate["lat"]
        zoom = candidate["zoom"]
        condition = candidate["condition"]
        address = candidate["address"]
        quiz_type = candidate.get("quiz_type", "미지정")
        
        result: Dict[str, object] = {
            "quiz_id": quiz_id,
            "quiz_type": quiz_type,
            "center": {"lon": lon, "lat": lat},
            "google_maps_url": f"https://www.google.com/maps/@{lat},{lon},{zoom}z",
            "condition": condition,
            "address": address,
        }
        
        return result
    except Exception as e:
        raise ValueError(f"오류 발생: {str(e)}")


if __name__ == "__main__":

    mcp.run(transport="streamable-http",path="https://geoquiz.fastmcp.app/mcp",)