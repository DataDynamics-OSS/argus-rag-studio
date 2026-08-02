// 지식베이스 생성/재인덱싱 설정 도움말 — 임베딩·청킹 개념 + 각 옵션·옵션값 설명.
// 다이얼로그 오른쪽 스크롤 패널에서 사용. 글꼴은 부모(text-sm)를 따른다.

function Section({ title, intro, children }: { title: string; intro: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <h4 className="mb-1 font-semibold text-foreground">{title}</h4>
      <p className="mb-3 text-muted-foreground">{intro}</p>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  )
}

function Item({ term, desc, values }: { term: string; desc: string; values?: [string, string][] }) {
  return (
    <div>
      <p className="font-medium text-foreground">{term}</p>
      <p className="text-muted-foreground">{desc}</p>
      {values && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground marker:text-muted-foreground/60">
          {values.map(([k, v]) => (
            <li key={k}>
              <span className="rounded bg-muted px-1 py-0.5 font-mono text-sm text-foreground">{k}</span>{" "}
              {v}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// 로컬(FastEmbed) 1024차원 모델별 특징·추천 상황
const LOCAL_MODELS: { id: string; tag: string; desc: string }[] = [
  {
    id: "intfloat/multilingual-e5-large",
    tag: "2.24GB · 다국어",
    desc: "100여 개 언어를 지원하고 한국어 품질이 우수합니다. 한국어·다국어 문서라면 1순위 추천. 검색 성능이 안정적이라 무난한 기본 선택이에요.",
  },
  {
    id: "jinaai/jina-embeddings-v3",
    tag: "2.29GB · 다국어/긴문맥",
    desc: "다국어를 지원하고 긴 문맥(최대 8192 토큰)에 강합니다. 한 청크가 길거나 긴 문서, 다국어가 섞인 자료에 적합해요.",
  },
  {
    id: "mixedbread-ai/mxbai-embed-large-v1",
    tag: "0.64GB · 영어",
    desc: "1024차원 중 가장 가벼워 다운로드·메모리 부담이 적습니다. 영어 위주이면서 리소스를 아끼고 싶을 때 좋아요.",
  },
  {
    id: "BAAI/bge-large-en-v1.5",
    tag: "1.2GB · 영어",
    desc: "영어 범용 임베딩의 표준급 모델. 영어 문서 검색의 무난한 기본 선택입니다.",
  },
  {
    id: "snowflake/snowflake-arctic-embed-l",
    tag: "1.02GB · 영어",
    desc: "검색(retrieval)에 최적화된 영어 모델. 영어 문서 검색 정확도를 끌어올리고 싶을 때.",
  },
  {
    id: "thenlper/gte-large",
    tag: "1.2GB · 영어",
    desc: "GTE 계열 영어 범용 모델. 영어 문서를 대상으로 한 또 다른 무난한 선택입니다.",
  },
]

export function CollectionConfigHelp() {
  return (
    <div className="text-sm leading-relaxed">
      <p className="mb-4 text-muted-foreground">
        RAG는 ① 파일에서 글자를 뽑고(파싱) ② 잘게 나눠(청킹) ③ 의미를 숫자로 바꿔(임베딩) 저장하고,
        질문이 오면 같은 방식으로 바꿔 가장 비슷한 조각을 찾아 답변 근거로 씁니다. 아래는 각 설정의 의미입니다.
      </p>

      <Section
        title="임베딩 (Embedding)"
        intro="문서·질문을 '의미를 담은 숫자 목록(벡터)'으로 바꾸는 단계예요. 의미가 비슷하면 숫자도 비슷해져서, 단어가 달라도('환불'↔'반품') 검색이 됩니다. 같은 지식베이스 안의 모든 벡터는 같은 방식으로 만들어야 하므로 생성 후에는 바꿀 수 없습니다(바꾸려면 전체 재인덱싱)."
      >
        <Item
          term="프로바이더"
          desc="임베딩을 실제로 만들어 주는 엔진을 고릅니다."
          values={[
            ["OpenAI 호환", "외부 임베딩 서버 사용(서버 URL 필요). 대규모·GPU 활용에 적합."],
            ["로컬", "서버 없이 이 앱이 직접 모델을 돌려 임베딩(최초 1회 모델 다운로드). 서버가 없는 환경에 권장."],
            ["hash", "의미 없는 더미 벡터를 만드는 테스트용. 실제 검색 품질은 없습니다(동작 확인 전용)."],
          ]}
        />
        <Item
          term="모델"
          desc="텍스트를 벡터로 바꾸는 임베딩 모델이에요. '로컬'은 지원 목록에서 고르면 됩니다(차원 자동). 'OpenAI 호환'은 모델명을 외울 필요 없이 서버 URL을 넣고 '모델 불러오기'를 누른 뒤 목록에서 선택합니다(직접 입력은 막혀 있어 오타·미지원 모델을 방지 — 목록엔 채팅 모델이 섞일 수 있으니 임베딩 모델을 고르세요). 한국어 문서는 multilingual-e5-large·jina-v3 같은 다국어 모델을 권장합니다."
        />
        <Item
          term="차원"
          desc="벡터의 길이(숫자 개수)예요. 모델마다 정해져 있어 모델과 맞아야 합니다(보통 1024). 사용자가 임의로 정하는 값이 아니라서 직접 입력은 막혀 있어요. 로컬은 모델 선택 시 자동으로 채워지고, OpenAI 호환은 '차원 감지' 버튼을 누르면 서버에 샘플을 한 번 보내 실제 차원을 읽어옵니다(모델을 바꾸면 다시 감지해야 합니다)."
        />
        <Item
          term="서버 URL"
          desc="OpenAI 호환 임베딩 서버 주소예요(예: http://host:8080/v1). 입력 후 '테스트' 버튼으로 연결을 확인하면(서버의 /health 호출), 모델 불러오기·차원 감지가 자동 실행돼 모델·차원이 채워집니다. URL을 바꾸면 테스트가 풀려 다시 확인해야 합니다. (로컬·hash는 서버가 필요 없어 표시되지 않습니다.)"
        />
        <Item
          term="거리 메트릭"
          desc="검색할 때 '질문과 문서가 얼마나 비슷한가'를 재는 방법이에요. 대부분 cosine이 정답입니다."
          values={[
            ["cosine", "두 벡터의 방향(각도)으로 유사도 측정. 정규화 임베딩의 표준."],
            ["l2", "두 벡터 사이의 직선 거리(유클리드)."],
            ["inner_product", "내적. 정규화된 벡터에서는 cosine과 같은 순위가 됩니다."],
          ]}
        />
        <Item
          term="리랭커"
          desc="1차 검색으로 추린 결과를 한 번 더 정밀하게 재정렬해 정확도를 높이는 단계예요. (쿼리 시점 설정이라 나중에 재인덱싱 없이 바꿀 수 있습니다.)"
          values={[
            ["none", "재정렬 안 함(가장 빠름)."],
            ["llm", "생성 LLM이 각 후보의 관련도를 판단해 재정렬(추가 서버 불필요)."],
            ["local", "이 앱이 직접 돌리는 FastEmbed cross-encoder 로 재정렬(서버 불필요, 최초 1회 모델 다운로드)."],
            ["cross_encoder", "전용 리랭크 서버로 정밀 재정렬(품질↑, 서버 필요)."],
          ]}
        />
      </Section>

      <Section
        title="로컬 임베딩 모델 고르기"
        intro="'로컬' 프로바이더는 아래 1024차원 모델 중에서 고릅니다('모델' 드롭다운과 동일). 한국어가 섞이면 다국어 모델(e5-large·jina-v3)을, 영어 위주면 나머지를 권장합니다. 모델은 최초 1회 다운로드 후 재사용됩니다."
      >
        {LOCAL_MODELS.map((m) => (
          <div key={m.id}>
            <p>
              <span className="rounded bg-muted px-1 py-0.5 font-mono text-sm text-foreground">{m.id}</span>{" "}
              <span className="text-muted-foreground">· {m.tag}</span>
            </p>
            <p className="text-muted-foreground">{m.desc}</p>
          </div>
        ))}
      </Section>

      <Section
        title="파싱 (Parsing)"
        intro="업로드한 파일(PDF·DOCX·HTML 등)에서 글자를 뽑아내는 첫 단계예요. 여기서 표가 깨지거나 글자를 못 읽으면 임베딩·검색·답변 어디서도 복구되지 않아, RAG 품질을 가장 크게 좌우합니다. 문서 종류에 맞게 고르세요. 설정을 바꾸면 전체 문서를 다시 처리(재인덱싱)해야 합니다. 추가 설치가 필요한 전략은 목록에 '(미설치)'로 표시되며, 설치하면 자동으로 활성화됩니다."
      >
        <Item
          term="파싱 전략"
          desc="표가 많은 문서라면 'layout' 이상을 권장합니다. 같은 표라도 'text'는 행·열이 뭉개지지만, 'layout'은 Markdown 표(| 헤더 | … |)로 살려내 임베딩·LLM이 정확히 이해합니다."
          values={[
            ["auto", "파일 유형에 맞는 전략을 자동 선택(권장 기본값). PDF→layout, HWP/HWPX→rhwp, 그 외→text. 한 지식베이스에 여러 형식을 섞어도 파일마다 알맞게 처리됩니다(의존성 없으면 text로 폴백)."],
            ["text", "순수 Python 로더로 형식별 추출(추가 설치 불필요). 다양한 형식을 처리하며 XLSX·PPTX·HWP·HWPX는 표를 Markdown으로 살립니다(PDF·DOCX 본문은 평문이라 표·다단·스캔본엔 약함)."],
            ["layout", "PDF 표를 Markdown 표로 직렬화 + 본문 추출. 표가 핵심인 보고서·명세서에 권장(pdfplumber 필요)."],
            ["docai", "문서 AI(Docling)로 레이아웃·표·읽기순서까지 복원. 다단·복잡 레이아웃에 강함(docling 필요)."],
            ["vlm", "페이지를 이미지로 보고 비전 LLM이 Markdown으로 변환. 스캔본·손글씨 등 최고 품질이나 느리고 비용·환각 주의(비전 모델 필요)."],
            ["rhwp", "한글 HWP/HWPX 전용 Rust 파서. text 전략도 HWP/HWPX를 순수 Python으로 처리하지만, rhwp는 복잡한 표·셀 병합 보존에 더 강합니다(rhwp_py 확장 빌드 필요)."],
          ]}
        />
      </Section>

      <Section
        title="청킹 (Chunking)"
        intro="긴 문서를 검색 단위인 '조각(청크)'으로 나누는 단계예요. 조각이 너무 크면 정밀도가 떨어지고, 너무 작으면 맥락이 끊깁니다. 설정을 바꾸면 전체 문서를 다시 처리(재인덱싱)해야 합니다."
      >
        <Item
          term="전략"
          desc="문서를 어떤 기준으로 자를지 정합니다."
          values={[
            ["auto", "파싱 결과 내용을 보고 자동 선택(권장 기본값). 표·헤딩이 있으면 markdown, 아니면 recursive로 자릅니다."],
            ["recursive", "문단→문장 구조를 살려 자르는 범용 기본값."],
            ["sentence", "문장을 끊지 않고 묶음. FAQ·QA처럼 문장 단위가 중요한 자료에 적합."],
            ["paragraph", "빈 줄(문단 경계)을 살려 문단을 끊지 않고 묶음. 산문·보고서처럼 문단이 의미 단위인 자료에 적합."],
            ["section", "섹션 헤더(마크다운 헤딩·번호·장/절)를 경계로 자르고 각 조각에 섹션 경로를 붙임. 헤딩이 있는 매뉴얼·규정·논문에 적합."],
            ["fixed", "구조를 무시하고 같은 길이로 자름(균일 길이가 필요할 때)."],
            ["markdown", "표·헤딩을 깨지 않고 보존하며 각 조각에 상위 헤딩 경로를 붙임. 파싱을 layout·docai·vlm(표를 Markdown으로)으로 한 문서에 권장."],
            ["semantic", "문장을 임베딩해 의미가 바뀌는 지점에서 자름(주제별로 묶임). 가장 정교하지만 인제스천 시 문장마다 임베딩이 필요해 비용·시간이 더 듭니다."],
          ]}
        />
        <Item
          term="단위"
          desc="청크 크기·오버랩을 무엇으로 셀지예요."
          values={[
            ["char", "글자 수(기본). 간단하지만 언어·코드마다 토큰 환산이 달라 임베딩 한도를 넘길 수 있음."],
            ["token", "임베딩 모델이 실제 세는 토큰 수(tiktoken). 보통 512토큰 한도를 정확히 지킬 때 안전(예: 크기 512, 오버랩 64). tiktoken 미설치 시 char로 폴백."],
          ]}
        />
        <Item
          term="청크 크기"
          desc="조각 하나의 최대 크기예요(단위에 따라 글자/토큰). 작으면 정밀하지만 맥락이 짧고, 크면 맥락은 길지만 덜 정밀합니다. char는 800~1200자, token은 256~512가 무난합니다. 오버랩을 포함해도 이 크기를 넘지 않으며(진짜 상한), 이 값의 10% 미만인 너무 짧은 조각은 노이즈를 막으려 이웃에 자동 병합됩니다."
        />
        <Item
          term="오버랩"
          desc="이웃한 조각끼리 겹치는 양이에요(단위는 위 '단위'를 따름 — 글자/토큰). 조각 경계에서 문맥이 끊기는 걸 줄여줍니다. 보통 청크 크기의 10~15%(예: 1000자면 150자)로 두며, 청크 크기보다 작아야 합니다. 겹치는 부분은 단어·문장 중간이 아니라 경계에서 깔끔하게 시작하도록 자동 정리됩니다. markdown·semantic은 헤딩·의미로 연속성을 확보하므로 오버랩을 쓰지 않습니다."
        />
      </Section>
    </div>
  )
}
