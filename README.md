# GeoQuiz MCP Server (VWorld)

VWorld(국토부 브이월드) 기반 위성지도 퀴즈 MCP 서버입니다. FastMCP로 배포하며, 조건에 맞는 퀴즈 생성/힌트/정답 제공 도구를 노출합니다.

# 서버 실행
server.py
```

## 사용 시나리오
- `request_quiz(condition, zoom?)`: 예) "한반도 도시 해안" → 조건에 맞는 좌표로 퀴즈 생성, VWorld 뷰어 링크/정적 이미지
- `request_hint(quiz_id, kind?)`: 퀴즈 힌트 제공
- `request_answer(quiz_id)`: 하이브리드(도로+명칭) 레이어 이미지(한반도) 또는 Google Maps 링크(해외)와 해설 제공
- 문제가 어렵다면 힌트를 요청하거나 API 상 위경도 좌표를 확인해 보세요.

## VWorld 연동
- 본 예제는 정적 이미지 API URL 형식을 예시로 제공합니다. 실제 엔드포인트/파라미터는 VWorld 공식 문서를 참고하여 조정하세요.
- 하이브리드 지도(도로+명칭) 사용 시 `basemap=hybrid`를 적용합니다.
- API 이슈로 인해 해외 지도의 경우 zoom 범위가 제한적입니다. 


## 주의
- 본 저장소에는 최소한의 좌표 샘플만 포함되어 있으며, 조건 파싱/출제 로직은 단순 키워드 매칭 기반입니다. 필요에 따라 데이터셋과 알고리즘을 확장하세요.
