"""Context loading for AGENTS.md and DA.json files."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import MCPServerInfo, ProjectContext

logger = logging.getLogger(__name__)


#====================================================================================================
# AI Nudge Phrases (Prompt Engineering Shortcuts)
#====================================================================================================

NUDGE_PHRASES = [
    # Careful & thorough
    "be careful and check your work",
    "double-check before making changes",
    "verify your changes after editing",
    "make sure to test thoroughly",
    "be conservative with changes",

    # Reasoning & thinking
    "think step-by-step",
    "explain your reasoning as you go",
    "show your work",
    "break down the problem first",
    "consider edge cases",
    "think about possible issues before you act",
    "analyze the implications",

    # Testing & verification
    "write tests first",
    "test edge cases",
    "include unit tests",
    "verify the fix works",
    "run the tests after changes",

    # Safety & confirmation
    "show me the diff first",
    "ask before destructive operations",
    "confirm before major changes",
    "preview changes before applying",

    # Efficiency & quality
    "minimize tool calls where possible",
    "batch related operations",
    "be concise but thorough",
    "focus on the key changes",

    # Exploration & alternatives
    "explore multiple approaches",
    "consider alternative solutions",
    "think creatively about this",
    "look for patterns in the codebase",

    # Code quality
    "follow the existing code style",
    "maintain consistency with the codebase",
    "add helpful comments",
    "keep the code readable",
    "use descriptive variable names",

    # Debugging & investigation
    "trace the root cause",
    "check related files too",
    "look for similar issues",
    "investigate thoroughly before fixing",
    "understand why this is happening",

    # Documentation & explanation
    "explain what you're doing",
    "document your changes",
    "add docstrings if needed",
    "make it clear for future readers",
]

# da_code generated nudge phrases (feel free to edit/extend)
NUDGE_PHRASES = '''Final answer: one clear sentence, followed by three concise supporting points.
Conclusion: one-line summary, then list the assumptions underlying that conclusion.
Return JSON: only include keys answer, steps, assumptions, confidence.
Summary: brief (1–2 sentences) then numbered steps to reproduce.
Short answer: then a concise explanation (no internal chain-of-thought).
Alternatives: offer three approaches, each with one-sentence pros and cons.
Patch: propose a minimal code change and show the unified diff.
Test case: provide a small unit test that would fail before the fix and pass after.
Security note: list potential security or privacy issues introduced by this change.
Confidence estimate: give a percentage and briefly justify it.
Clarify if ambiguous: list plausible interpretations and ask one clarifying question.
TL;DR: one-liner then a detailed 5-step plan.
Commands: recommended command-line steps to reproduce the issue.
Checklist: actionable items to verify before deployment.
Troubleshoot: short guide with likely causes and fixes.
Optimize: list three performance optimization ideas and estimated impact for each.
Next action: explain the single best next step a developer should take in one sentence.
Migration plan: concise plan with rollback steps included.
User impact: summarize expected user-visible behavior change in one paragraph.
Edge cases: describe edge cases to watch for and how to test them quickly.
Default config: suggest a reasonable default configuration and explain why.
Minimal repro: provide a self-contained minimal reproducible example illustrating the problem.
API usage: show a short code snippet demonstrating recommended usage.
Files to change: list the minimal set of files and specific edits needed.
PR checklist: numbered review checklist items for a pull request.
Compatibility: explain compatibility concerns with existing versions and mitigations.
Rollout: give an incremental rollout plan with metrics to monitor.
CI commands: one-liner commands to run basic validation tests in CI.
Memory tradeoffs: propose three ways to reduce memory usage with tradeoffs for each.
Expected logs: provide an example of expected log output after the change.
Relevant tests: list the most relevant tests to run and why they matter.
IO example: give an example input and expected output for the new behavior.
Safeguard: propose a safe default to prevent accidental data loss and explain it.
Rationale: summarize why this change is needed in two sentences.
Code review: short comment focusing on readability improvements.
Error handling: concise suggestion to improve error handling and a code example.
Impact map: list upstream or downstream components that might be affected.
Threat model: one succinct sentence describing the security threat model.
Metric: recommend a single metric to track for regressions and why.
Parse example: small example showing how to parse the output programmatically.
Feature flags: list configuration flags that could be toggled for testing.
API demo: compact curl command demonstrating the API change.
Failure modes: three possible failure modes and short mitigations for each.
Back-compat test: suggest a back-compatibility test and how to automate it.
Docker snippet: minimal Dockerfile snippet to reproduce the environment.
Env vars: list environment variables that influence behavior and their defaults.
Algorithm note: one-paragraph explanation of the algorithmic change.
Library compare: short comparative table of two libraries to consider.
Benchmark: suggest one simple benchmark to run and the expected baseline.
Dependency rationale: concise explanation of why the chosen dependency is appropriate.
Migrations: list required data migrations and a safe order of operations.
Follow-ups: prioritized list of follow-up tasks after this change.
Log config: sample log-level configuration suitable for debugging.
Health-check: describe a minimal health-check endpoint to detect regressions.
Performance summary: summarize CPU, memory, and latency characteristics.
Mocking example: show how to mock an external service in tests.
Privacy: list privacy considerations for storing user-provided data and mitigations.
Rollback: succinct rollback command or procedure for emergencies.
Secure review: brief checklist for secure code review of this change.
Timeouts: suggest a conservative default timeout and rationale.
Scalability: one-sentence statement of how this affects scalability.
Migration steps: concise migration path for existing users with examples.
Observability: list minimal observability additions to detect production issues.
Structured logs: short example of structured JSON logs for the new feature.
Canary plan: propose a canary deployment strategy and key success metrics.
Repro steps: step-by-step guide to reproduce the bug locally.
Unit tests: list three unit tests that validate the most important behavior.
Pseudo-code: offer a simple pseudo-code outline of the new algorithm.
Legal note: short comment on licensing or patent implications, if any.
Input validation: set of input validation checks to add with examples.
Permissions: recommend file and directory permissions for safe operation.
Setup script: small bash script to automate local setup for contributors.
Dependency list: list dependencies with exact versions used for testing.
Ecosystem note: one-paragraph compatibility statement with the ecosystem.
User comms: concise plan for communicating the change to end users.
Automated checks: suggest automated checks to run in CI and expected outcomes.
Benchmark script: brief benchmarking script and how to interpret results.
Misconfigs: list common misconfigurations and how to detect them in logs.
Rollback steps: short explanation of how to rollback a failed deploy step.
Graceful degrade: example of graceful degradation for partial failures.
Test assertions: minimal set of assertions to add to unit tests.
Property test: example of a property-based test case to include.
Simplicity note: one-sentence explanation of why this approach is simpler.
Security hardening: three security hardening recommendations relevant to this change.
Data retention: concise summary of data retention implications.
Compliance: short note on GDPR or regional compliance considerations.
Seed data: compact script to seed test data for integration tests.
Dashboards: most relevant monitoring dashboards to update and why.
Prometheus query: example Prometheus query to detect a regression.
Thread-safety: brief explanation of thread-safety concerns and fixes.
Concurrency: list concurrency pitfalls and short mitigation strategies.
Mobile note: one-line compatibility note for mobile clients, if applicable.
HTTP statuses: clear example of expected HTTP status codes and meanings.
Network debug: short debugging steps for common network-related failures.
Defensive check: example defensive check before performing write operations.
Extensibility: concise summary of how to extend this feature later.
Acceptance criteria: three acceptance criteria for shipping this change.
Feature flag config: sample feature flag configuration for staged rollout.
Schema checklist: short checklist for database schema migrations.
Backup steps: list backups and verification steps required before migration.
SQL validation: compact SQL snippet to validate migrated data integrity.
Release notes: brief outline of release notes to publish.
Stakeholders: list stakeholders to notify and the short reason for each.
Compatibility shim: minimal example of a compatibility shim if needed.
Worst-case: succinct explanation of the worst-case failure scenario.
QA steps: quick manual QA steps testers should run before release.
UX summary: one-paragraph description of how UX changes for users.
API versioning: example change in API contract and recommended versioning.
Metrics keys: list keys to include in metrics emitted for this feature.
Mock time: short example of how to mock time in tests for determinism.
Dev mode: compact guide to running the app in development mode.
Profiling targets: top 5 code paths to instrument for performance profiling.
Error wrapping: concise snippet showing proper error wrapping and logging.
Sanitization: small example demonstrating input sanitization.
Data formats: list accepted data formats and the canonical representation used.
Cache default: one-line recommendation for a sensible default cache size.
Cache policy: brief explanation of caching strategy and eviction policy.
Security headers: list security headers to add to HTTP responses and why.
Lint command: short command to run linting and formatting checks locally.
Parallel tests: example config for running tests in parallel safely.
Orchestration pitfalls: common pitfalls when deploying to orchestrators and fixes.
Experiment flags: small example of using feature flags for experiments.
Load testing: concise plan for load testing and expected targets.
Sync vs async: list tradeoffs between synchronous and asynchronous processing here.
Shutdown: scripted example of graceful shutdown for the service.
Queue metrics: example metrics to track request queues and worker utilization.
Intermittent debug: steps for reproducing intermittent failures and collecting traces.
Consistency rationale: concise rationale for eventual consistency, if used.
Memory leak debug: step-by-step guide to debug memory leaks in this module.
Log retention: minimum retention period for logs required for audits.
Batch failures: example of safely handling partial failures in batch jobs.
Changelog template: template for documenting API changes in the changelog.
Static analysis: most relevant static analysis tools to run on this code.
Error surfacing: one-line summary of how errors are surfaced to the client.
README snippet: small example of how to document configuration in README.
Backward checks: quick checks to ensure backward compatibility of public APIs.
Schema versioning: concise note on how to handle schema versioning for stored data.
DB index: example of an index to add to databases for performance.
Latency impact: expected latency impacts of adding this feature and mitigations.
User benefit: one-sentence summary of the primary user benefit of this change.
Concurrency primitive: short snippet demonstrating safe concurrency primitives to use.
Pipeline perms: list required permissions for CI/CD pipelines to deploy safely.
Security scan: brief checklist for security scanning before shipping.
Serverless note: example serverless deployment note if applicable.
Retry guidance: error codes consumers should handle and recommended retries.
Data model: short explanation of the data model changes and examples.
Cloud compatibility: concise note on compatibility with major cloud providers.
Test datasets: list test datasets used for validating correctness and size.
Telemetry events: quick example of telemetry events to emit for user actions.
Cost impact: one-sentence statement of how this affects cost per request.
Migration pitfalls: common migration pitfalls and a simple way to detect them.
API response validation: short example showing how to validate external API responses.
Client versioning: concise note on how to version client libraries for this change.
Prod-like local: steps to locally reproduce production-like configuration safely.
Error message guideline: one-line guideline for writing clear error messages for users.
Rate limit example: short example of rate-limiting strategy and thresholds.
Fallbacks: list fallback behaviors when external services are unavailable.
Multi-tenant test: succinct explanation of how to test multi-tenant interactions.
Smoke checklist: minimal checklist for post-deploy smoke testing.
Flag key-values: key-value pairs to add to feature flags for experimentation.
Backoff example: short example of how to implement exponential backoff retries.
Model choice: concise explanation of why the data model was chosen.
Alert thresholds: monitoring alerts to create and thresholds to use.
User impact metric: one-line summary of how to measure user impact of this change.
Dry-run script: example of a simple migration script with safety checks.
Boundary tests: list boundary conditions to include in unit tests.
Key management: short explanation of encryption choices and key management.
Secret injection: minimal example of secure secret injection in CI.
Build commands: commands to locally rebuild artifacts and run smoke tests.
Atomic updates: concise explanation of how to handle partial updates atomically.
Integration test: short example invoking the full stack in an integration test.
Runbooks: list operational runbooks to include for on-call engineers.
Escalation note: succinct note on when to escalate to core platform teams.
Pagination example: compact example of API pagination and cursor usage.
Static asset headers: caching headers to use for static assets and rationale.
Schema evolution: brief example of how to do schema evolution without downtime.
Accessibility checklist: short checklist of accessibility considerations for UI changes.
Cert rotation: steps to validate certificate rotation in production.
Client retry default: one-sentence recommendation for default retry policy in clients.
Blue/green: short example of how to perform blue/green deployment.
Container scanners: security scanners to run against container images.
Docs update: concise guide to update documentation for public APIs.
Design rationale: one-line summary of why this design was chosen over alternatives.
Backpressure cases: list likely corner cases where backpressure might occur.
Tracing example: brief example of how to instrument distributed tracing.
Race condition tests: short explanation of how to test for race conditions.
Audit log fields: list fields to include in audit logs and why they are important.
Migration safety: one-paragraph explanation of the migration safety strategy.
Health-check example: sample health-check endpoint response and interpretation.
Corruption repro: short steps to reproduce data corruption scenarios safely.
Compaction plan: concise plan for database vacuuming or compaction if needed.
Secure patterns: short example of secure coding patterns to follow here.
Initial monitoring: minimum viable monitoring needed for the first week after release.
Partial migration: one-line explanation of how to roll forward a partial migration.
API stubbing: small example of how to stub external APIs in tests.
Backup impact: list the impact on backup size and retention after this change.
Regulatory note: short note on regulatory reporting implications if applicable.
Fuzz test: minimal example of input fuzz testing to add to CI.
Dry-run steps: steps to perform a dry-run of migration without applying changes.
Log verbosity: concise recommendation for logging verbosity in production.
API negotiation: example of API version negotiation and deprecation strategy.
Secrets check: quick checks to confirm that secrets are not leaked in logs.
Traffic ramp: short plan for gradually increasing traffic during rollout.
Schema constraints: minimal example of how to validate schema constraints in code.
Flag placements: areas where feature flags should be added for safer rollout.
Rate limit scope: concise note on how to enforce rate limits per user vs per org.
SLO guidance: one-line recommendation for SLO targets impacted by this change.
Usability tests: small usability tests to ensure minimal UX regressions.
Timeout mocking: short sample of how to mock timeouts in unit tests.
Maintainability: brief explanation of why the new approach is maintainable.
QA toggles: list configuration toggles to include for QA and staging environments.
Internal comms: one-sentence suggested communication blurb for internal teams.
E2E latency: short example of how to measure end-to-end latency.
Alert tuning: likely false positives in monitoring and how to tune alerts.
Client metrics: concise example of how to instrument client-side metrics.
Compliance checklist: minimal checklist for compliance reviews before release.
Integration partners: key integration partners to notify about the API change.
A/B test flags: short example of how to use feature flags to A/B test behavior.
Analytics note: one-line description of the user journey impact for analytics.
SDK regen: steps to regenerate API client SDKs after schema changes.
Circuit breaker: small example of how to add circuit breakers around calls.
Auth debug logs: brief note on which logs to collect for debugging authentication issues.
Perf sample size: sample sizes to include in performance tests for statistical power.
Bug triage: short explanation of how to triage and prioritize bugs after rollout.
Doc comments: concise example of code comments to help future maintainers.
CI acceptance: minimal acceptance tests to automate in CI before merging PRs.
Quota changes: one-line statement of resource quota changes needed in cloud environments.
Chaos testing: short example of how to perform chaos testing for resilience.
License checks: quick checks to ensure third-party licenses are compatible.
Encrypt at rest: concise explanation of how to validate encryption at rest mechanisms.
Rate limit under load: small example showing how to validate API rate limits under load.
Dashboard metrics: precise metrics to include in a feature dashboard.
Tech debt: one-sentence reason why this approach reduces technical debt.
Migration locks: short example of how to manage schema migrations with locks.
Cost estimate: list expected costs in cloud resources and how to estimate them.
Approval list: focused list of stakeholders to include in release approval.
Local debug: guide to set up local debugging with IDE breakpoints.
UX copy: small UX copy changes needed and suggested phrasing for each.
Telemetry IDs: concise example of how to annotate telemetry with correlation IDs.
Fallback behavior: one-paragraph explanation of the fallback behavior for failures.
Post-deploy smoke: simple smoke-test commands to run immediately after deployment.
Backward compat: one-line recommendation for preserving backward compatibility during rollout.
Schema drift: brief explanation of how to detect schema drift between environments.
Autoscale thresholds: important thresholds for autoscaling policies related to this change.
File upload test: short example of how to test file uploads in a CI environment.
Key rotation: concise plan to rotate keys or credentials if the change requires it.
Dev portal: API endpoints to update in the developer portal and why.
User-facing errors: one-sentence guideline for meaningful error messages to users.
Log security: short note on how to secure logs that may contain user identifiers.
Follow-up PRs: list expected follow-up PRs to tidy related modules after merge.
Next step: final one-line recommended next action for the engineering team.'''.split('\n')

#====================================================================================================
# File/Directory Utilities
#====================================================================================================

def get_file_emoji(filename: str) -> str:
    """Get emoji for file type."""
    name_lower = filename.lower()
    if name_lower.endswith(('.py', '.pyw')):
        return "🐍"
    elif name_lower.endswith(('.js', '.jsx', '.ts', '.tsx')):
        return "🟨"
    elif name_lower.endswith(('.md', '.markdown')):
        return "📖"
    elif name_lower.endswith(('.json', '.yaml', '.yml', '.toml')):
        return "⚙️"
    elif name_lower.endswith(('.env', '.gitignore', '.dockerignore')):
        return "🔧"
    elif name_lower.endswith(('.txt', '.log')):
        return "📝"
    elif name_lower.endswith(('.sh', '.bash', '.zsh')):
        return "🔸"
    elif name_lower.endswith(('.html', '.htm', '.css')):
        return "🌐"
    elif name_lower.endswith(('.sql', '.db', '.sqlite')):
        return "🗄️"
    elif name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
        return "🖼️"
    else:
        return "📄"


#====================================================================================================
# Directory Context
#====================================================================================================

class DirectoryContext:
    """Provides intelligent directory context for the agent with activity-based previews."""

    def __init__(self, working_dir: str):
        """Initialize directory context."""
        self.working_dir = Path(working_dir)
        self._cache_timestamp = None
        self._cached_listing = None

    def get_directory_listing(self) -> Tuple[str, float]:
        """Get integrated directory listing with subdirectory previews and time deltas."""
        try:
            listing = []
            current_time = time.time()

            # Get files/dirs, skip ignored patterns
            ignored = {'.git', '__pycache__', '.vscode', 'node_modules'}

            # Get activity scores for directories
            directory_scores = {}
            for item in self.working_dir.iterdir():
                if (item.is_dir() and
                    not item.name.startswith('.') and
                    item.name not in ignored):
                    score = self._calculate_activity_score(item, current_time)
                    directory_scores[item.name] = score

            # Process all items with integrated subdirectory previews
            for item in sorted(self.working_dir.iterdir()):
                if item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                    continue
                if item.name in ignored:
                    continue

                try:
                    if item.is_dir():
                        # Directory with activity score and time delta
                        activity_score = directory_scores.get(item.name, float('inf'))
                        time_delta = self._format_time_delta(activity_score)

                        listing.append(f"📁 {item.name}/ ({time_delta})")

                        # Add subdirectory preview if it's one of the active directories
                        if activity_score < 7 * 86400:  # Only show preview for dirs active within 7 days
                            preview = self._get_subdirectory_preview(item.name, max_files=3)
                            if preview:
                                listing.append(preview)
                    else:
                        # File with size and modification time
                        stat = item.stat()
                        mod_delta = current_time - stat.st_mtime
                        time_str = self._format_time_delta(mod_delta)

                        size = stat.st_size
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024*1024:
                            size_str = f"{size//1024}KB"
                        else:
                            size_str = f"{size//(1024*1024)}MB"

                        emoji = get_file_emoji(item.name)
                        listing.append(f"{emoji} {item.name} ({size_str}, {time_str})")

                except (OSError, PermissionError):
                    continue

            if not listing:
                listing.append("(empty directory)")

            result = "\n".join(listing)
            timestamp = time.time()

            # Update cache
            self._cached_listing = result
            self._cache_timestamp = timestamp

            return result, timestamp

        except Exception as e:
            logger.error(f"Failed to get directory listing: {e}")
            return f"📁 {self.working_dir} (unable to read)", time.time()

    def check_changes(self, cache_timestamp: float) -> Optional[str]:
        """Check if directory changed since timestamp. Returns update message if changed."""
        if not cache_timestamp:
            return None

        try:
            # Quick check: any file newer than cache?
            for item in self.working_dir.iterdir():
                if item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                    continue
                if item.name in {'.git', '__pycache__', '.vscode', 'node_modules'}:
                    continue

                try:
                    if item.stat().st_mtime > cache_timestamp:
                        new_listing, _ = self.get_directory_listing()
                        return f"📁 Directory updated:\n{new_listing}\n\n"
                except (OSError, PermissionError):
                    continue

            return None

        except Exception as e:
            logger.error(f"Failed to check directory changes: {e}")
            return None

    def _calculate_activity_score(self, dir_path: Path, current_time: float) -> float:
        """Calculate activity score using max(avg_file_activity, directory_activity)."""
        try:
            dir_stat = dir_path.stat()
            directory_update_delta = current_time - dir_stat.st_mtime

            # Get all file update deltas
            file_deltas = []
            for file_path in dir_path.rglob('*'):
                if (file_path.is_file() and
                    not file_path.name.startswith('.') and
                    file_path.name not in {'__pycache__', '.pyc', '.pyo'}):
                    file_delta = current_time - file_path.stat().st_mtime
                    file_deltas.append(file_delta)

            if not file_deltas:
                return directory_update_delta

            avg_file_activity = sum(file_deltas) / len(file_deltas)

            # Scoring formula: max of average file activity vs directory activity
            score = max(avg_file_activity, directory_update_delta)
            return score

        except (OSError, PermissionError):
            return float('inf')  # Inaccessible = lowest priority

    def _get_subdirectory_preview(self, subdir_name: str, max_files: int = 4) -> str:
        """Get preview of subdirectory contents with emoji file types."""
        subdir_path = self.working_dir / subdir_name
        if not subdir_path.exists() or not subdir_path.is_dir():
            return ""

        preview_lines = []
        file_count = 0
        total_files = 0

        try:
            # Get files sorted by size (larger files often more important)
            files = []
            for item in subdir_path.iterdir():
                if item.is_file() and not item.name.startswith('.'):
                    try:
                        size = item.stat().st_size
                        files.append((item.name, size))
                        total_files += 1
                    except (OSError, PermissionError):
                        continue

            # Sort by size descending, then by name
            files.sort(key=lambda x: (-x[1], x[0]))

            # Show top files with emojis
            for filename, size in files[:max_files]:
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024*1024:
                    size_str = f"{size//1024}KB"
                else:
                    size_str = f"{size//(1024*1024)}MB"

                emoji = get_file_emoji(filename)
                preview_lines.append(f"  └── {emoji} {filename} ({size_str})")
                file_count += 1

            # Add summary if there are more files
            if total_files > max_files:
                remaining = total_files - max_files
                preview_lines.append(f"  └── ... and {remaining} more files")

        except (OSError, PermissionError):
            preview_lines.append(f"  └── (unable to read {subdir_name})")

        return "\n".join(preview_lines)

    def _format_time_delta(self, seconds: float) -> str:
        """Format time delta in human readable form."""
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds/60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds/3600)}h ago"
        else:
            return f"{int(seconds/86400)}d ago"


#====================================================================================================
# Project Context Loader
#====================================================================================================


class ContextLoader:
    """Loads project context from AGENTS.md and MCP server info from DA.json."""

    def __init__(self, project_root: Optional[str] = None):
        """Initialize context loader with project root directory."""
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.agents_md_path = self.project_root / "AGENTS.md"
        self.da_json_path = self.project_root / "DA.json"

    def load_project_context(self) -> Optional[ProjectContext]:
        """Load project context from AGENTS.md file."""
        try:
            if not self.agents_md_path.exists():
                logger.warning(f"AGENTS.md not found at {self.agents_md_path}")
                return None

            with open(self.agents_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if not content.strip():
                logger.warning("AGENTS.md is empty")
                return None

            # Extract project name and description from markdown
            project_name = self._extract_project_name(content)
            description = self._extract_description(content)
            instructions = self._extract_instructions(content)

            context = ProjectContext(
                project_name=project_name,
                description=description,
                instructions=instructions,
                file_content=content
            )

            logger.info(f"Loaded project context from {self.agents_md_path}")
            return context

        except Exception as e:
            logger.error(f"Failed to load AGENTS.md: {e}")
            return None

    def load_mcp_servers(self) -> List[MCPServerInfo]:
        """Load MCP server information from DA.json file and add built-in servers."""
        servers = []

        # Load external MCP servers from DA.json
        try:
            if not self.da_json_path.exists():
                logger.warning(f"DA.json not found at {self.da_json_path}")
                return servers

            with open(self.da_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            mcp_servers = data.get('mcp_servers', [])

            for server_data in mcp_servers:
                try:
                    server = MCPServerInfo(**server_data)
                    servers.append(server)
                except Exception as e:
                    logger.error(f"Invalid MCP server data: {server_data}, error: {e}")
                    continue

            logger.info(f"Loaded {len(servers)} total MCP servers ({len(mcp_servers)} from DA.json + 1 built-in)")
            return servers

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in DA.json: {e}")
            return servers
        except Exception as e:
            logger.error(f"Failed to load DA.json: {e}")
            return servers

    def _extract_project_name(self, content: str) -> Optional[str]:
        """Extract project name from markdown content."""
        lines = content.split('\n')

        for line in lines:
            line = line.strip()
            # Look for first H1 heading
            if line.startswith('# '):
                return line[2:].strip()

        return None

    def _extract_description(self, content: str) -> Optional[str]:
        """Extract project description from markdown content."""
        lines = content.split('\n')
        description_lines = []
        found_title = False

        for line in lines:
            line = line.strip()

            # Skip empty lines before finding title
            if not found_title and not line:
                continue

            # Found the title (H1)
            if line.startswith('# '):
                found_title = True
                continue

            # Stop at next heading or section
            if found_title and (line.startswith('#') or line.startswith('##')):
                break

            # Collect description lines
            if found_title:
                description_lines.append(line)

        description = '\n'.join(description_lines).strip()
        return description if description else None

    def _extract_instructions(self, content: str) -> Optional[str]:
        """Extract instructions from markdown content."""
        # Look for sections with 'instruction' in the heading
        lines = content.split('\n')
        instructions_lines = []
        in_instructions = False

        for line in lines:
            line_lower = line.lower().strip()

            # Check if this is an instructions heading
            if line_lower.startswith('#') and 'instruction' in line_lower:
                in_instructions = True
                continue

            # Stop at next heading
            if in_instructions and line.strip().startswith('#'):
                break

            # Collect instruction lines
            if in_instructions:
                instructions_lines.append(line)

        instructions = '\n'.join(instructions_lines).strip()
        return instructions if instructions else None

    def create_sample_da_json(self) -> None:
        """Create a sample DA.json file with common MCP servers."""
        sample_data = {
            "mcp_servers": [
                {
                    "name": "search",
                    "url": "http://localhost:8080/search",
                    "port": 8003,
                    "description": "Web search MCP server",
                    "tools": ["web_search", "extract_content"]
                }
            ],
            "default_working_directory": ".",
            "agent_settings": {
                "model": "gpt-40",
                "temperature": 0.7,
                "max_tokens": None,
                "require_confirmation": True
            }
        }

        try:
            with open(self.da_json_path, 'w', encoding='utf-8') as f:
                json.dump(sample_data, f, indent=2)

            logger.info(f"Created sample DA.json at {self.da_json_path}")
        except Exception as e:
            logger.error(f"Failed to create sample DA.json: {e}")

    def create_sample_agents_md(self) -> None:
        """Create a sample AGENTS.md file."""
        sample_content = """# Project Name

Brief description of your project goes here.

## Agent Instructions

Instructions for the da_code AI agent on how to work with this project:

### Development Workflow
- Preferred coding patterns and conventions
- Testing approach (unit tests, integration tests, etc.)
- Git workflow and commit message style
- Code review process

### Project Structure
- Key directories and their purposes
- Important configuration files
- Entry points and main modules
- Documentation locations

### Tools and Technologies
- Programming languages and frameworks
- Build tools and package managers
- Development dependencies
- Deployment tools

## Coding Standards

### Style Guidelines
- Code formatting preferences
- Naming conventions
- Comment and documentation style
- Error handling patterns

### Best Practices
- Performance considerations
- Security guidelines
- Accessibility requirements
- Browser/platform compatibility

## Agent Behavior

### Preferred Actions
- Always run tests after code changes
- Use specific linting/formatting tools
- Follow specific commit patterns
- Ask for confirmation before major changes

### Project Context
- Domain-specific knowledge the agent should know
- Business logic and requirements
- Integration points with external systems
- Known issues or technical debt

## Important Files

- `src/main.py` - Application entry point
- `tests/` - Test suite location
- `requirements.txt` - Python dependencies
- `README.md` - Project documentation
- `.env.example` - Environment configuration template
"""

        try:
            with open(self.agents_md_path, 'w', encoding='utf-8') as f:
                f.write(sample_content)

            logger.info(f"Created sample AGENTS.md at {self.agents_md_path}")
            print(f"\n📝 Created sample AGENTS.md file at {self.agents_md_path}")
            print("💡 Edit this file to provide context and instructions for the AI agent")
        except Exception as e:
            logger.error(f"Failed to create sample AGENTS.md: {e}")


#====================================================================================================
# MCP Server Health Check and Tool Discovery, TODO: should these be deleted?
#====================================================================================================


async def check_mcp_server_health(server: MCPServerInfo) -> bool:
    """Check if an MCP server is healthy and responsive."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            health_url = f"{server.url.rstrip('/')}/health"
            async with session.get(health_url, timeout=5) as response:
                return response.status == 200

    except Exception as e:
        logger.error(f"Health check failed for {server.name}: {e}")
        return False


async def discover_mcp_tools(server: MCPServerInfo) -> List[str]:
    """Discover available tools from an MCP server."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            tools_url = f"{server.url.rstrip('/')}/mcp"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list"
            }

            async with session.post(tools_url, json=payload, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get('result', {})
                    tools = result.get('tools', [])
                    return [tool.get('name', '') for tool in tools if tool.get('name')]

    except Exception as e:
        logger.error(f"Tool discovery failed for {server.name}: {e}")

    return []