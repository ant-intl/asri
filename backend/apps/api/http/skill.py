"""
Skill API views — filesystem-backed.

Directory layout::

    {SKILLS_ROOT}/{tenant_id}/skills/{skill_name}/SKILL.md

All CRUD operations are tenant-scoped: each request resolves the tenant from
``request.tenant_id`` (set by middleware) and operates only within that
tenant's skill directory.
"""
import json
import logging
import os
import re

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.utils.skill_paths import get_tenant_skills_dir

logger = logging.getLogger(__name__)

# Skill name pattern: English letters, numbers, underscores, and hyphens only
SKILL_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _tenant_id(request) -> str:
    """Tenant ID from middleware-set ``request.tenant_id``, falling back to ``'example'``."""
    tenant_id = getattr(request, 'tenant_id', None)
    return tenant_id if isinstance(tenant_id, str) and tenant_id else 'example'


def _tenant_skills_base(request) -> str:
    """Return absolute path to the current tenant's skills directory."""
    return get_tenant_skills_dir(_tenant_id(request))


def validate_skill_name(name: str) -> str | None:
    """Validate skill name format. Returns error message if invalid, None if valid."""
    if not name:
        return 'name is required'
    if not SKILL_NAME_PATTERN.match(name):
        return (
            'name must contain only English letters, numbers, underscores (_), '
            'and hyphens (-). Example: "refund_process" or "account-management"'
        )
    return None


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _parse_skill_md(filepath: str) -> dict | None:
    """Parse a SKILL.md file and return a dict with metadata + content.

    Returns ``None`` if the file is missing or has invalid frontmatter.
    """
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError):
        return None

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", raw, re.DOTALL)
    if not m:
        return None

    frontmatter = m.group(1)
    body = m.group(2).strip()  # noqa: F841

    name_m = re.search(r"^name\s*:\s*(.+)", frontmatter, re.MULTILINE)
    desc_m = re.search(r"^description\s*:\s*(.+)", frontmatter, re.MULTILINE)
    active_m = re.search(r"^is_active\s*:\s*(.+)", frontmatter, re.MULTILINE)

    if not name_m:
        return None

    name = name_m.group(1).strip()
    description = desc_m.group(1).strip() if desc_m else ""
    is_active = active_m.group(1).strip().lower() == "true" if active_m else True

    return {
        "name": name,
        "description": description,
        "is_active": is_active,
        "content": raw,
    }


def _build_skill_md(name: str, description: str, content: str, is_active: bool = True) -> str:
    """Build a complete SKILL.md string with frontmatter."""
    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"is_active: {str(is_active).lower()}\n"
        f"---\n\n"
    )
    return frontmatter + content


def _update_frontmatter_field(filepath: str, field: str, value: str) -> bool:
    """Update a single field in the YAML frontmatter of a SKILL.md file."""
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError):
        return False

    m = re.match(r"^(---\s*\n.*?\n---)(\s*\n?.*)", raw, re.DOTALL)
    if not m:
        return False

    header = m.group(1)
    body = m.group(2)

    # Replace or add the field in the frontmatter block
    pattern = re.compile(rf"^{re.escape(field)}\s*:.*", re.MULTILINE)
    if pattern.search(header):
        header = pattern.sub(f"{field}: {value}", header)
    else:
        # Insert before the closing ---
        header = header.rstrip("\n-")
        header = header.rstrip() + f"\n{field}: {value}\n---"

    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(header + body)
        return True
    except OSError:
        return False


def _skill_dir(name: str, base_dir: str) -> str | None:
    """Return the absolute path to a skill directory, or None if name is invalid."""
    if not SKILL_NAME_PATTERN.match(name):
        return None
    return os.path.join(base_dir, name)


def _list_skills_from_fs(base_dir: str) -> list[dict]:
    """Scan *base_dir* and return skill dicts."""
    if not os.path.isdir(base_dir):
        return []
    result = []
    for entry in os.scandir(base_dir):
        if not entry.is_dir():
            continue
        md_path = os.path.join(entry.path, "SKILL.md")
        parsed = _parse_skill_md(md_path)
        if parsed is None:
            continue
        try:
            stat = os.stat(md_path)
        except OSError:
            stat = None

        result.append({
            "skill_id": entry.name,
            "name": parsed["name"],
            "description": parsed["description"],
            "content": parsed["content"],
            "is_active": parsed["is_active"],
            "metadata": {},
            "gmt_create": _stat_time(stat.st_birthtime if stat else 0),
            "gmt_modified": _stat_time(stat.st_mtime if stat else 0),
        })
    result.sort(key=lambda s: s["name"])
    return result


def _stat_time(t: float) -> str:
    """Convert a stat timestamp to ISO format string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat() if t else ""


def _re_register_skills(tenant_id: str, base_dir: str) -> None:
    """Re-scan and re-register skills for a single tenant."""
    from apps.integrations.skill.filesystem_skill_loader import scan_skills as _scan
    from apps.integrations.skill.base import SkillRegistry
    # Clear only this tenant's bucket
    SkillRegistry._skills.pop(tenant_id, None)
    _scan(base_dir=base_dir, tenant_id=tenant_id)


# ============================================================================
# Views
# ============================================================================


@method_decorator(csrf_exempt, name='dispatch')
class SkillListView(View):
    """
    List and create skills (filesystem-backed, tenant-scoped).

    GET  /chatbot/api/admin/skills/
    POST /chatbot/api/admin/skills/
    """

    async def get(self, request: HttpRequest) -> JsonResponse:
        """List all skills for the current tenant."""
        base_dir = _tenant_skills_base(request)
        skills = _list_skills_from_fs(base_dir)
        # Support ?is_active=true/false filter
        is_active_param = request.GET.get('is_active', None)
        if is_active_param is not None:
            target = is_active_param.lower() == 'true'
            skills = [s for s in skills if s["is_active"] == target]
        return JsonResponse({
            "skills": skills,
            "total": len(skills),
            "page": 1,
            "page_size": len(skills) or 20,
        })

    async def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new skill by writing SKILL.md under the tenant's skills directory."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        name = data.get('name', '').strip()
        content = data.get('content', '').strip()
        description = data.get('description', '').strip()
        is_active = data.get('is_active', True)

        # Validate
        name_error = validate_skill_name(name)
        if name_error:
            return JsonResponse({'error': name_error}, status=400)
        if not content:
            return JsonResponse({'error': 'content is required'}, status=400)

        base_dir = _tenant_skills_base(request)
        d = _skill_dir(name, base_dir)
        if d is None:
            return JsonResponse({'error': 'Invalid skill name'}, status=400)
        if os.path.isdir(d):
            return JsonResponse({'error': f'Skill "{name}" already exists'}, status=400)

        # Create directory and SKILL.md
        try:
            os.makedirs(d, exist_ok=True)
            md_content = _build_skill_md(name, description, content, is_active)
            md_path = os.path.join(d, "SKILL.md")
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(md_content)
        except OSError as e:
            return JsonResponse({'error': f'Failed to create skill: {e}'}, status=500)

        # Register to SkillRegistry
        _re_register_skills(_tenant_id(request), base_dir)

        return JsonResponse({
            "skill_id": name,
            "name": name,
            "description": description,
            "is_active": is_active,
            "gmt_create": "",
        }, status=201)


@method_decorator(csrf_exempt, name='dispatch')
class SkillDetailView(View):
    """
    Read, update, delete a single skill (tenant-scoped).

    GET    /chatbot/api/admin/skills/{name}/
    PUT    /chatbot/api/admin/skills/{name}/
    DELETE /chatbot/api/admin/skills/{name}/
    """

    def _locate(self, skill_id: str, base_dir: str) -> str | None:
        """Resolve skill_id (name) to absolute SKILL.md path, or None."""
        d = _skill_dir(skill_id, base_dir)
        if d is None:
            return None
        md_path = os.path.join(d, "SKILL.md")
        if not os.path.isfile(md_path):
            return None
        return md_path

    async def get(self, request: HttpRequest, skill_id: str) -> JsonResponse:
        """Get skill detail."""
        base_dir = _tenant_skills_base(request)
        md_path = self._locate(skill_id, base_dir)
        if md_path is None:
            return JsonResponse({'error': 'Skill not found'}, status=404)
        parsed = _parse_skill_md(md_path)
        if parsed is None:
            return JsonResponse({'error': 'Invalid SKILL.md'}, status=500)
        try:
            stat = os.stat(md_path)
        except OSError:
            stat = None
        return JsonResponse({
            "skill_id": skill_id,
            "name": parsed["name"],
            "description": parsed["description"],
            "content": parsed["content"],
            "is_active": parsed["is_active"],
            "metadata": {},
            "gmt_create": _stat_time(stat.st_birthtime if stat else 0),
            "gmt_modified": _stat_time(stat.st_mtime if stat else 0),
        })

    async def put(self, request: HttpRequest, skill_id: str) -> JsonResponse:
        """Update skill — rewrite SKILL.md."""
        base_dir = _tenant_skills_base(request)
        md_path = self._locate(skill_id, base_dir)
        if md_path is None:
            return JsonResponse({'error': 'Skill not found'}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        # Read existing content and merge
        parsed = _parse_skill_md(md_path)
        if parsed is None:
            return JsonResponse({'error': 'Invalid SKILL.md'}, status=500)

        name = data.get('name', '').strip() or parsed["name"]
        description = data.get('description', '').strip() if 'description' in data else parsed["description"]
        content = data.get('content', '').strip() if 'content' in data else None
        is_active = data.get('is_active', parsed["is_active"]) if 'is_active' in data else parsed["is_active"]

        try:
            md_content = _build_skill_md(name, description, content or parsed["content"], is_active)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(md_content)
        except OSError as e:
            return JsonResponse({'error': f'Failed to update skill: {e}'}, status=500)

        _re_register_skills(_tenant_id(request), base_dir)

        # Re-read and return
        try:
            stat = os.stat(md_path)
        except OSError:
            stat = None
        return JsonResponse({
            "skill_id": skill_id,
            "name": name,
            "description": description,
            "content": md_content,
            "is_active": is_active,
            "metadata": {},
            "gmt_create": _stat_time(stat.st_birthtime if stat else 0),
            "gmt_modified": _stat_time(stat.st_mtime if stat else 0),
        })

    async def delete(self, request: HttpRequest, skill_id: str) -> JsonResponse:
        """Delete a skill directory."""
        base_dir = _tenant_skills_base(request)
        d = _skill_dir(skill_id, base_dir)
        if d is None:
            return JsonResponse({'error': 'Invalid skill name'}, status=400)
        if not os.path.isdir(d):
            return JsonResponse({'error': 'Skill not found'}, status=404)

        import shutil
        try:
            shutil.rmtree(d)
        except OSError as e:
            return JsonResponse({'error': f'Failed to delete skill: {e}'}, status=500)

        # Remove from registry (tenant-scoped)
        from apps.integrations.skill.base import SkillRegistry
        tid = _tenant_id(request)
        bucket = SkillRegistry._skills.get(tid, {})
        bucket.pop(skill_id.lower(), None)

        return JsonResponse({'success': True})


@method_decorator(csrf_exempt, name='dispatch')
class SkillRefreshView(View):
    """
    Re-scan filesystem and re-register all skills for the current tenant.

    POST /chatbot/api/admin/skills/{name}/refresh/
    """

    async def post(self, request: HttpRequest, skill_id: str) -> JsonResponse:
        """Re-scan and re-register the given skill."""
        base_dir = _tenant_skills_base(request)
        d = _skill_dir(skill_id, base_dir)
        if d is None or not os.path.isdir(d):
            return JsonResponse({'error': 'Skill not found'}, status=404)

        tid = _tenant_id(request)
        _re_register_skills(tid, base_dir)

        from apps.integrations.skill.base import SkillRegistry
        count = len(SkillRegistry._skills.get(tid, {}))
        return JsonResponse({'status': 'refreshed', 'skills_count': count})


@method_decorator(csrf_exempt, name='dispatch')
class SkillEnableView(View):
    """
    Enable a skill by setting ``is_active: true`` in frontmatter.

    POST /chatbot/api/admin/skills/{name}/enable/
    """

    async def post(self, request: HttpRequest, skill_id: str) -> JsonResponse:
        base_dir = _tenant_skills_base(request)
        md_path = SkillDetailView()._locate(skill_id, base_dir)
        if md_path is None:
            return JsonResponse({'error': 'Skill not found'}, status=404)
        if not _update_frontmatter_field(md_path, "is_active", "true"):
            return JsonResponse({'error': 'Failed to update SKILL.md'}, status=500)

        _re_register_skills(_tenant_id(request), base_dir)
        return JsonResponse({'success': True, 'skill_id': skill_id, 'message': 'Skill enabled'})


@method_decorator(csrf_exempt, name='dispatch')
class SkillDisableView(View):
    """
    Disable a skill by setting ``is_active: false`` in frontmatter.

    POST /chatbot/api/admin/skills/{name}/disable/
    """

    async def post(self, request: HttpRequest, skill_id: str) -> JsonResponse:
        base_dir = _tenant_skills_base(request)
        md_path = SkillDetailView()._locate(skill_id, base_dir)
        if md_path is None:
            return JsonResponse({'error': 'Skill not found'}, status=404)
        if not _update_frontmatter_field(md_path, "is_active", "false"):
            return JsonResponse({'error': 'Failed to update SKILL.md'}, status=500)

        _re_register_skills(_tenant_id(request), base_dir)
        return JsonResponse({'success': True, 'skill_id': skill_id, 'message': 'Skill disabled'})


@method_decorator(csrf_exempt, name='dispatch')
class SkillUploadView(View):
    """
    Upload and install a skill from a zip package (tenant-scoped).

    POST /chatbot/api/admin/skills/upload/

    The zip must contain a valid ``SKILL.md`` at its root
    with YAML frontmatter containing a ``name`` field.

    Supports multipart/form-data with a ``file`` field.
    """

    async def post(self, request: HttpRequest) -> JsonResponse:
        # --- validate file ---------------------------------------------------
        zip_file = request.FILES.get('file')
        if zip_file is None:
            return JsonResponse({'error': 'No file provided. Use multipart field "file".'}, status=400)

        if not zip_file.name.endswith('.zip'):
            return JsonResponse({'error': 'File must be a .zip archive.'}, status=400)

        # --- read zip into memory --------------------------------------------
        import zipfile
        import io
        import re as _re

        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_file.read()))
        except zipfile.BadZipFile:
            return JsonResponse({'error': 'Invalid zip file.'}, status=400)

        # --- locate SKILL.md (support nested folder) -------------------------
        names = zf.namelist()
        skill_md_entry = None
        strip_prefix = ''  # common subdirectory prefix to strip

        if 'SKILL.md' in names:
            skill_md_entry = 'SKILL.md'
        else:
            # Check if all files share a single top-level directory
            top_dirs = set()
            for n in names:
                parts = n.split('/')
                if len(parts) > 1 and parts[0]:
                    top_dirs.add(parts[0])
            if len(top_dirs) == 1:
                prefix = next(iter(top_dirs)) + '/'
                candidate = prefix + 'SKILL.md'
                if candidate in names:
                    skill_md_entry = candidate
                    strip_prefix = prefix

        if skill_md_entry is None:
            return JsonResponse({'error': 'Zip must contain SKILL.md at root.'}, status=400)

        # --- extract name from frontmatter -----------------------------------
        try:
            fm_raw = zf.read(skill_md_entry).decode('utf-8')
        except (KeyError, UnicodeDecodeError) as e:
            return JsonResponse({'error': f'Cannot read SKILL.md: {e}'}, status=400)

        fm_match = _re.match(r'^---\s*\n(.*?)\n---', fm_raw, _re.DOTALL)
        if not fm_match:
            return JsonResponse({'error': 'SKILL.md must have YAML frontmatter (---).'}, status=400)

        name_match = _re.search(r'^name\s*:\s*(.+)', fm_match.group(1), _re.MULTILINE)
        if not name_match:
            return JsonResponse({'error': 'SKILL.md frontmatter must have a "name" field.'}, status=400)

        name = name_match.group(1).strip()
        name_error = validate_skill_name(name)
        if name_error:
            return JsonResponse({'error': f'Invalid skill name in SKILL.md: {name_error}'}, status=400)

        # --- check existing --------------------------------------------------
        base_dir = _tenant_skills_base(request)
        target_dir = os.path.join(base_dir, name)
        if os.path.isdir(target_dir):
            return JsonResponse({'error': f'Skill "{name}" already exists.'}, status=400)

        # --- extract (strip subdirectory prefix if any) ----------------------
        try:
            os.makedirs(target_dir, exist_ok=True)
            if strip_prefix:
                for member in zf.namelist():
                    if not member.startswith(strip_prefix):
                        continue
                    rel_path = member[len(strip_prefix):]
                    if not rel_path:
                        continue  # skip directory entry itself
                    target = os.path.join(target_dir, rel_path)
                    if member.endswith('/'):
                        os.makedirs(target, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(member) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
            else:
                zf.extractall(target_dir)
        except Exception as e:
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)
            return JsonResponse({'error': f'Failed to extract zip: {e}'}, status=500)
        finally:
            zf.close()

        # --- register --------------------------------------------------------
        _re_register_skills(_tenant_id(request), base_dir)

        return JsonResponse({
            'success': True,
            'skill_id': name,
            'name': name,
            'message': f'Skill "{name}" installed successfully.',
        }, status=201)
