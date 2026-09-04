from urllib.parse import unquote

import pytest

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
    response = authenticated_client.get(href)
    assert response.status_code == 200
    assert response.content == path.read_bytes()
    disposition = unquote(response.headers['content-disposition'])
    assert disposition.startswith('attachment;')
    assert doc.original_name in disposition


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
