from urllib.parse import unquote
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Document, Task, TaskDocument


@pytest.fixture
def attachment(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr('app.web.router.document_archive_root', lambda: tmp_path)
    task = Task(title='Synthetic attachment task', task_type='operational_task',
                category='Operação', subcategory='Pedido', status='new', priority='normal')
    db_session.add(task)
    db_session.flush()
    path = tmp_path / 'test.msg'
    path.write_bytes(b'synthetic message attachment')
    doc = Document(title='Test message', original_name='Histórico teste.msg',
                   file_name='test.msg', storage_provider='local', storage_path=str(path),
                   document_type='task_attachment', classification='task_attachment',
                   source='task', entry_channel='task_upload', status='received', task_id=task.id)
    db_session.add(doc)
    db_session.flush()
    db_session.add(TaskDocument(task_id=task.id, document_id=doc.id))
    db_session.commit()
    return task, doc, path


def test_attachment_links_and_authenticated_download(authenticated_client, attachment):
    task, doc, path = attachment
    href = f'/v2-clean/documents/{doc.id}/file?inline=0'
    for url in [f'/v2-clean/tasks/{task.id}/detail', f'/v2-clean/documents/{doc.id}']:
        page = authenticated_client.get(url)
        assert page.status_code == 200
        assert f'href="{href}"' in page.text
        assert 'Descarregar anexo' in page.text
    task_page = authenticated_client.get(f'/v2-clean/tasks/{task.id}/detail')
    assert f'href="/v2-clean/documents/{doc.id}?return_to=' in task_page.text
    assert '>Abrir</a>' in task_page.text
    response = authenticated_client.get(href)
    assert response.status_code == 200
    assert response.content == path.read_bytes()
    disposition = unquote(response.headers['content-disposition'])
    assert disposition.startswith('attachment;')
    assert doc.original_name in disposition


@pytest.mark.parametrize(
    ("filename", "content_type", "preview_kind"),
    [
        ("prova.pdf", "application/pdf", "pdf"),
        ("prova.png", "image/png", "image"),
    ],
)
def test_task_attachment_pdf_and_image_open_inline_from_document_detail(
    authenticated_client, attachment, db_session, filename, content_type, preview_kind
):
    _, doc, old_path = attachment
    new_path = old_path.with_name(filename)
    new_path.write_bytes(b"synthetic preview")
    old_path.unlink()
    doc.title = filename
    doc.original_name = filename
    doc.file_name = filename
    doc.storage_path = str(new_path)
    db_session.commit()

    page = authenticated_client.get(f"/v2-clean/documents/{doc.id}")
    assert page.status_code == 200
    assert f'data-preview-src="/v2-clean/documents/{doc.id}/file?inline=1"' in page.text
    assert f'data-preview-kind="{preview_kind}"' in page.text
    assert ">Pré-visualizar</button>" in page.text

    inline_response = authenticated_client.get(
        f"/v2-clean/documents/{doc.id}/file?inline=1"
    )
    assert inline_response.status_code == 200
    assert inline_response.headers["content-type"] == content_type
    assert unquote(inline_response.headers["content-disposition"]).startswith("inline;")

    download_response = authenticated_client.get(
        f"/v2-clean/documents/{doc.id}/file?inline=0"
    )
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == content_type
    assert unquote(download_response.headers["content-disposition"]).startswith("attachment;")


def test_non_previewable_task_attachment_opens_detail_without_automatic_download(
    authenticated_client, attachment
):
    task, doc, _ = attachment
    task_page = authenticated_client.get(f"/v2-clean/tasks/{task.id}/detail")
    assert f'href="/v2-clean/documents/{doc.id}?return_to=' in task_page.text
    assert f'href="/v2-clean/documents/{doc.id}/file?inline=1"' not in task_page.text

    detail_page = authenticated_client.get(f"/v2-clean/documents/{doc.id}")
    assert detail_page.status_code == 200
    assert "data-preview-src=" not in detail_page.text
    assert ">Pré-visualizar</button>" not in detail_page.text
    assert f'/v2-clean/documents/{doc.id}/file?inline=0' in detail_page.text


def test_attachment_download_requires_login(client, attachment):
    _, doc, _ = attachment
    response = client.get(f'/v2-clean/documents/{doc.id}/file?inline=0', follow_redirects=False)
    assert response.status_code == 303
    assert '/login' in response.headers['location']


def test_attachment_download_keeps_document_permissions(authenticated_client, attachment, monkeypatch):
    _, doc, _ = attachment
    monkeypatch.setattr('app.web.router.can_view_documentation', lambda _: False)
    response = authenticated_client.get(f'/v2-clean/documents/{doc.id}/file?inline=0', follow_redirects=False)
    assert response.status_code == 303
    assert 'forbidden' in response.headers['location']


def test_missing_attachment_has_visible_message(authenticated_client, attachment):
    _, doc, path = attachment
    path.unlink()
    response = authenticated_client.get(f'/v2-clean/documents/{doc.id}/file?inline=0')
    assert response.status_code == 200
    assert 'O ficheiro anexado não foi encontrado no arquivo.' in response.text


def test_removed_attachment_has_no_download_link(authenticated_client, attachment, db_session):
    _, doc, _ = attachment
    doc.status = 'removed'
    db_session.commit()
    response = authenticated_client.get(f'/v2-clean/documents/{doc.id}')
    assert f'/v2-clean/documents/{doc.id}/file?inline=0' not in response.text
    response = authenticated_client.get(f'/v2-clean/documents/{doc.id}/file?inline=0', follow_redirects=False)
    assert response.status_code == 303


def test_detail_attachment_upload_returns_to_open_documents_and_persists(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr("app.web.router.document_archive_root", lambda: tmp_path)
    task = Task(
        title="Upload no detalhe",
        task_type="operational_task",
        category="Operação",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/attachments",
        data={"return_url": f"/v2-clean/tasks/{task.id}/detail"},
        files={"attachments": ("prova.txt", b"persistido", "text/plain")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(
        f"/v2-clean/tasks/{task.id}/detail?document_linked=1#task-documents"
    )
    document = db_session.scalar(select(Document).where(Document.task_id == task.id))
    assert document is not None
    assert Path(document.storage_path).read_bytes() == b"persistido"
    page = authenticated_client.get(response.headers["location"])
    assert 'id="task-documents" open' in page.text
    assert "prova.txt" in page.text
    assert f'/v2-clean/documents/{document.id}/file?inline=0' in page.text
