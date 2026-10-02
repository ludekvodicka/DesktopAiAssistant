import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import psutil
from .config import data_dir
from .text import IMAGE_SCHEMA, SCHEMA, prompt, question_prompt, translation_prompt, validate_answer, validate_result, validate_translation


CLAUDE_ARGS = ["-p", "--tools", "", "--safe-mode", "--no-session-persistence", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--permission-mode", "dontAsk", "--permission-prompts", "none", "--no-chrome"]
CODEX_ARGS = ["--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only", "--json",
              "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
              "--disable", "shell_tool", "--disable", "hooks", "--disable", "plugins", "--disable", "multi_agent",
              "--disable", "apps", "--disable", "unified_exec", "--disable", "multi_agent_v2",
              "--disable", "browser_use", "--disable", "browser_use_external", "--disable", "in_app_browser",
              "--disable", "image_generation", "--disable", "view_image", "--disable", "skill_search"]


class Cancelled(Exception):
    pass


def command(name):
    executable = shutil.which(name + ".exe")
    if executable:
        return [executable]
    if name == "codex":
        launcher = shutil.which("codex.cmd")
        node = shutil.which("node.exe")
        if launcher and node:
            entry = Path(launcher).parent / "node_modules/@openai/codex/bin/codex.js"
            if entry.is_file():
                return [node, str(entry)]
    raise RuntimeError(f"{name} CLI was not found. Install its official CLI and sign in.")


def terminate(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=3)
    except psutil.NoSuchProcess:
        pass


def run_process(args, cancel, cwd=None, env=None, input_text="", timeout=90):
    process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW, shell=False)
    started = time.monotonic()
    first = True
    try:
        while True:
            if cancel.is_set():
                raise Cancelled("Cancelled")
            if time.monotonic() - started > timeout:
                raise TimeoutError("The operation timed out")
            try:
                out, err = process.communicate(input_text if first else None, timeout=0.15)
                if process.returncode:
                    raise RuntimeError(f"Process exited with code {process.returncode}: {err[-1200:]}")
                if len(out) > 2_000_000:
                    raise ValueError("Provider output is too large")
                return out
            except subprocess.TimeoutExpired:
                first = False
    finally:
        if process.poll() is None:
            terminate(process)
        process.communicate()


def provider_env(name):
    env = dict(os.environ)
    for key in list(env):
        if key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_CODE_OAUTH_TOKEN") or key.startswith(("CODEX_", "CLAUDE_CODE_", "JAMAT_")):
            env.pop(key)
    if name == "codex":
        home = data_dir() / "codex"
        home.mkdir(exist_ok=True)
        env["CODEX_HOME"] = str(home)
    return env


def invoke(config, request, schema, cancel, image=None, timeout=90):
    provider = config["provider"]
    jobs = data_dir() / "jobs"
    jobs.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="job-", dir=jobs, ignore_cleanup_errors=True) as folder:
        args, stdin = command(provider), request
        if provider == "claude":
            args += CLAUDE_ARGS + ["--json-schema", json.dumps(schema)]
            if image is None:
                args += ["--output-format", "json"]
            else:
                # The CLI takes images only as stream-json content blocks, and that input requires stream-json output.
                args += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
                stdin = json.dumps({"type": "user", "message": {"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(image).decode()}},
                    {"type": "text", "text": request}]}}) + "\n"
        elif provider == "codex":
            schema_file = Path(folder) / "schema.json"
            schema_file.write_text(json.dumps(schema), "utf-8")
            args += ["exec"]
            if image is not None:
                png = Path(folder) / "source.png"
                png.write_bytes(image)
                # -i takes several values, so an option must follow it, never the "-" prompt marker.
                args += ["-i", str(png)]
            args += CODEX_ARGS + ["--output-schema", str(schema_file)]
        else:
            raise ValueError("Unknown provider")
        if config["models"][provider]:
            args += ["--model", config["models"][provider]]
        if provider == "codex":
            args += ["-"]
        output = run_process(args, cancel, folder, provider_env(provider), stdin, timeout)
    if provider == "claude":
        if image is None:
            envelope = json.loads(output)
        else:
            events = [json.loads(line) for line in output.splitlines() if line.strip()]
            envelope = next((x for x in reversed(events) if x.get("type") == "result"), None)
            if envelope is None:
                raise RuntimeError("Claude returned no result")
        if envelope.get("is_error") or envelope.get("subtype") != "success":
            raise RuntimeError("Claude did not complete successfully: " + str(envelope.get("result", ""))[:500])
        result = envelope.get("structured_output")
        return json.loads(envelope["result"]) if result is None else result
    elif provider == "codex":
        events = [json.loads(line) for line in output.splitlines() if line.strip()]
        if not any(x.get("type") == "turn.completed" for x in events) or any(x.get("type") in ("error", "turn.failed") for x in events):
            raise RuntimeError("Codex did not complete successfully")
        messages = [x["item"]["text"] for x in events if x.get("type") == "item.completed" and x.get("item", {}).get("type") == "agent_message"]
        if not messages:
            raise ValueError("Codex returned no final text")
        return json.loads(messages[-1])
    else:
        raise ValueError("Unknown provider")


def transform(config, action, text, cancel):
    request = prompt(action, text, config["nativeLanguage"], config["socialLowercase"], config["rules"][action])
    return validate_result(text, invoke(config, request, SCHEMA, cancel))


def translate(config, source, cancel):
    request = translation_prompt(config["nativeLanguage"], source["format"], source["text"], config["rules"]["translate"])
    schema = IMAGE_SCHEMA if source["format"] == "image" else SCHEMA
    return validate_translation(source, invoke(config, request, schema, cancel, source["image"], timeout=180))



def answer(config, source, translation, conversation, question, cancel):
    request = question_prompt(config["nativeLanguage"], source, translation, conversation, question)
    return validate_answer(invoke(config, request, SCHEMA, cancel, timeout=180))


def clean_jobs():
    # Called at start under the single-instance lock, so no job folder is in use; a crash can leave a region PNG behind.
    for folder in (data_dir() / "jobs").glob("job-*"):
        shutil.rmtree(folder, ignore_errors=True)
