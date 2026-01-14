"""GeoQuiz MCP server for VWorld satellite-based map quizzes with Streamable HTTP support."""

import json
import os
from typing import Dict, AsyncGenerator

from fastmcp import FastMCP
from fastmcp.resources import Resource, ResourceTemplate
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


# ============================================================================
# RESOURCES - VWorld 스키마, 퀴즈 포맷, API 문서
# ============================================================================

QUIZ_SCHEMA_RESOURCE = """{
  "quiz_record": {
    "quiz_id": "string (e.g., quiz-1, quiz-2)",
    "candidate": {
      "condition": "string - 사용자 요청 문제 조건",
      "address": "string - 역지오코딩으로 얻은 주소",
      "quiz_type": "string - 행정구역명(도/시/군/구/읍/면/동) 또는 자연지형(산/강/섬)",
      "lat": "float - 위도",
      "lon": "float - 경도",
      "zoom": "int - VWorld 지도 확대 레벨",
      "tags": "array - 선택사항"
    }
  }
}"""

VWORLD_API_RESOURCE = """{
  "service": "VWorld Static Image API",
  "endpoint": "https://api.vworld.kr/req/image",
  "documentation": "https://www.vworld.kr/dev/v4dv_apiDocumentation_v3.jsp?menuId=20041",
  "parameters": {
    "service": "always 'image' for static maps",
    "request": "always 'getmap' for static maps",
    "key": "string - Your VWorld API Key (from key.env)",
    "center": "string - 'lon,lat' format, e.g., '127.0276,37.4979'",
    "zoom": "int - map zoom level (7-16 typical)",
    "basemap": "string - 'PHOTO' for satellite, 'BASE' for base map",
    "format": "string - 'png' or 'jpeg'",
    "size": "string - 'width,height' format, e.g., '1024,1024'"
  },
  "basemap_types": {
    "PHOTO": "Satellite/aerial imagery (recommended for GeoQuiz)",
    "BASE": "Standard map with labels",
    "GRAY": "Grayscale base map",
    "MIDNIGHT": "Dark themed map"
  },
  "example_url": "https://api.vworld.kr/req/image?service=image&request=getmap&key=YOUR_KEY&center=127.0276,37.4979&zoom=15&basemap=PHOTO&format=png&size=1024,1024"
}"""

TOOL_USAGE_GUIDE = """{
  "tools": [
    {
      "name": "create_map_quiz",
      "description": "VWorld 위성이미지로 지도 퀴즈 생성",
      "usage": "LLM이 위치와 문제 유형을 선택하면 이 도구가 지도 이미지 URL을 생성합니다",
      "returns": {
        "type": "string message",
        "contains": [
          "quiz_id: 향후 hint/answer 요청에 필요",
          "markdown link: 지도 이미지 접근 URL",
          "question_template: '어떤 (세부유형)인가요?' 형식"
        ]
      }
    },
    {
      "name": "request_hint",
      "description": "특정 퀴즈의 힌트 제공",
      "input": {
        "quiz_id": "create_map_quiz에서 반환된 quiz_id"
      },
      "returns": {
        "quiz_id": "string",
        "quiz_type": "string - 정답 유형",
        "center": "object {lon: float, lat: float}",
        "condition": "string - 원본 요청"
      }
    },
    {
      "name": "request_answer",
      "description": "퀴즈의 정답 및 상세 정보 제공",
      "input": {
        "quiz_id": "create_map_quiz에서 반환된 quiz_id"
      },
      "returns": {
        "quiz_id": "string",
        "quiz_type": "string - 정답 유형",
        "center": "object {lon: float, lat: float}",
        "google_maps_url": "string - 정답 위치 지도 링크",
        "condition": "string - 원본 요청",
        "address": "string - 역지오코딩 주소"
      }
    }
  ]
}"""

DEPLOYMENT_INFO = """{
  "server": "GeoQuiz MCP Server (VWorld)",
  "version": "1.0.0",
  "transport": "Streamable HTTP",
  "endpoint": "https://geoquiz.fastmcp.app/mcp",
  "architecture": "Stateless via Streamable HTTP (MCP protocol level)",
  "session_management": "In-memory QuizStore (quiz_id-based access)",
  "requirements": {
    "python": "3.8+",
    "fastmcp": ">=0.1.0",
    "geopy": ">=2.3.0",
    "requests": ">=2.28.0"
  },
  "environment": {
    "VWORLD_API_KEY": "Set in key.env - Required for VWorld API access",
    "default": "DEMO_KEY (limited functionality)"
  },
  "features": [
    "Dynamic quiz generation from coordinates",
    "VWorld satellite image integration",
    "Korean address reverse geocoding",
    "Adaptive zoom levels for different administrative divisions",
    "Google Maps integration for answer verification"
  ]
}"""


# Register resources
@mcp.resource("geoquiz://quiz-format")
def get_quiz_schema() -> str:
    """Get the quiz record data structure used by GeoQuiz."""
    return QUIZ_SCHEMA_RESOURCE


@mcp.resource("geoquiz://vworld-api")
def get_vworld_api_docs() -> str:
    """Get VWorld Static Image API documentation and parameters."""
    return VWORLD_API_RESOURCE


@mcp.resource("geoquiz://tool-usage-guide")
def get_tool_usage() -> str:
    """Get detailed usage guide for all GeoQuiz MCP tools."""
    return TOOL_USAGE_GUIDE


@mcp.resource("geoquiz://deployment")
def get_deployment_info() -> str:
    """Get deployment configuration and server information."""
    return DEPLOYMENT_INFO


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
    """클라이언트 LLM이 선택한 위치로 지도 퀴즈를 생성합니다 (Streamable HTTP 방식).

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
        print(f"[GeoQuiz] create_map_quiz 호출: condition={condition}, lat={lat}, lon={lon}, zoom={zoom}")
        
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
def request_hint(quiz_id: str) -> Dict[str, object]:
    """quiz_id의 힌트를 제공합니다 (Streamable HTTP 방식).
    힌트에 정답과 동일하거나 유사한 단어가 포함될 경우 다른 힌트를 제시하시오.
    """
    try:
        print(f"[GeoQuiz] request_hint 호출: quiz_id={quiz_id}")
        record = store.get(quiz_id)
        candidate = record["candidate"]
        quiz_type = candidate.get("quiz_type", "미지정")
        lon, lat = candidate["lon"], candidate["lat"]
        condition = candidate["condition"]
        
        hint: Dict[str, object] = {
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
    """정답(하이브리드 지도 링크 및 해설)을 제공합니다 (Streamable HTTP 방식)."""
    try:
        print(f"[GeoQuiz] request_answer 호출: quiz_id={quiz_id}")
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
    # Streamable HTTP 방식으로 MCP 서버 실행
    # 배포 도메인: https://geoquiz.fastmcp.app/mcp
    # Stateless 방식으로 작동
    mcp.run(
        transport="streamable-http",
        path="/mcp",
    )