// SPDX-License-Identifier: MIT
//! rhwp_py — rhwp(Rust HWP 파서, MIT)에 대한 PyO3 바인딩.
//!
//! HWP 5.0 바이너리와 HWPX 를 모두 파싱하며(자동 판별), 페이지 단위로 텍스트 또는
//! Markdown(표 보존)을 추출한다. RAG 인제스천의 ``rhwp`` 파싱 전략에서 사용한다.
//!
//! 노출 함수:
//!   - ``extract_markdown(data: bytes) -> str`` : 표를 Markdown 표로 보존(권장)
//!   - ``extract_text(data: bytes) -> str``     : 평문 텍스트
//!   - ``extract_markdown_pages_with_images(data: bytes) -> list[(str, list[int])]`` :
//!     페이지별 (Markdown — ``[[RHWP_IMAGE:n]]`` 토큰 유지, [bin_data_id...]).
//!     페이지 내 토큰 n(1-based)이 해당 페이지 id 목록의 순서와 대응한다 —
//!     인제스천이 토큰을 이미지 위치 마커로 치환해 청크↔이미지 정밀 연결에 쓴다.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

use rhwp_core::wasm_api::HwpDocument;

/// rhwp Markdown 출력에 남는 이미지 토큰(``[[RHWP_IMAGE:n]]``)을 제거한다(RAG 텍스트용).
fn strip_image_tokens(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(start) = rest.find("[[RHWP_IMAGE:") {
        out.push_str(&rest[..start]);
        match rest[start..].find("]]") {
            Some(end) => rest = &rest[start + end + 2..],
            None => {
                rest = "";
                break;
            }
        }
    }
    out.push_str(rest);
    out
}

fn parse(data: &[u8]) -> PyResult<HwpDocument> {
    HwpDocument::from_bytes(data)
        .map_err(|e| PyRuntimeError::new_err(format!("HWP/HWPX 파싱 실패: {e}")))
}

/// 표를 Markdown 표로 보존한 전체 문서 Markdown 을 반환한다(페이지를 빈 줄로 연결).
#[pyfunction]
fn extract_markdown(data: &[u8]) -> PyResult<String> {
    let doc = parse(data)?;
    let mut parts: Vec<String> = Vec::new();
    for page in 0..doc.page_count() {
        let md = doc
            .extract_page_markdown_native(page)
            .map_err(|e| PyRuntimeError::new_err(format!("페이지 {page} Markdown 추출 실패: {e:?}")))?;
        let md = strip_image_tokens(&md);
        let md = md.trim();
        if !md.is_empty() {
            parts.push(md.to_string());
        }
    }
    Ok(parts.join("\n\n"))
}

/// 페이지별 (Markdown(이미지 토큰 유지), [bin_data_id...]) 목록을 반환한다.
///
/// 토큰 ``[[RHWP_IMAGE:n]]`` 은 페이지마다 1부터 다시 시작하며, n 은 그 페이지의
/// bin_data_id 목록 순서(1-based)와 대응한다. HWPX 의 bin_data_id 는
/// ``binaryItemIDRef``(예 "image1")의 숫자부, HWP 5.0 은 BinData 레코드 ID 다.
#[pyfunction]
fn extract_markdown_pages_with_images(data: &[u8]) -> PyResult<Vec<(String, Vec<u16>)>> {
    let doc = parse(data)?;
    let mut pages: Vec<(String, Vec<u16>)> = Vec::new();
    for page in 0..doc.page_count() {
        let (md, images) = doc
            .extract_page_markdown_with_images_native(page)
            .map_err(|e| PyRuntimeError::new_err(format!("페이지 {page} Markdown 추출 실패: {e:?}")))?;
        let ids = images.iter().map(|(_, _, _, id)| *id).collect();
        pages.push((md, ids));
    }
    Ok(pages)
}

/// 평문 텍스트 전체를 반환한다(페이지를 개행으로 연결).
#[pyfunction]
fn extract_text(data: &[u8]) -> PyResult<String> {
    let doc = parse(data)?;
    let mut parts: Vec<String> = Vec::new();
    for page in 0..doc.page_count() {
        let text = doc
            .extract_page_text_native(page)
            .map_err(|e| PyRuntimeError::new_err(format!("페이지 {page} 텍스트 추출 실패: {e:?}")))?;
        let text = text.trim();
        if !text.is_empty() {
            parts.push(text.to_string());
        }
    }
    Ok(parts.join("\n"))
}

#[pymodule]
fn rhwp_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_markdown, m)?)?;
    m.add_function(wrap_pyfunction!(extract_text, m)?)?;
    m.add_function(wrap_pyfunction!(extract_markdown_pages_with_images, m)?)?;
    // 바인딩 버전 = RAG Studio 버전(Cargo.toml). rhwp 코어는 npm @rhwp/core 와 동일 릴리스.
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("__rhwp_version__", "0.7.18")?;
    m.add("__rhwp_rev__", "93862a4e16df59834ebce46d91e948cd739208e9")?;
    Ok(())
}
