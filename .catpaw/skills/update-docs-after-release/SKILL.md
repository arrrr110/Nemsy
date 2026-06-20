---
name: update-docs-after-release
description: Update MVP.md and README.md after pushing a new git version. Analyzes recent commits to check off completed features in MVP checklist and add new usage examples to README. Use when user mentions updating documentation, releasing a version, or after git push.
---

# Update Documentation After Release

## Purpose

After pushing a new git version, automatically synchronize project documentation (MVP.md and README.md) with actual code changes, following the principle of minimal edits.

## When to Use

Trigger this skill when:
- User mentions "更新文档" or "update docs"
- User says they just pushed a new version
- User asks to sync MVP checklist with recent changes
- User mentions updating README with new features

## Workflow

### Step 1: Analyze Recent Changes

```bash
# Get commits since last documented version
git log --oneline --since="1 week ago" --no-merges
```

Review commit messages and changed files to identify:
- **New features implemented**: Look for `feat:` or feature-related commits
- **Bugs fixed**: Look for `fix:` or bug-related commits  
- **Features from MVP待实现 that are now done**: Match commits to MVP checklist items

### Step 2: Update MVP.md Checklist

**File**: `design/MVP.md`

**Location**: Section "八、当前已实现 vs 待实现"

**Update rules**:
1. Move completed items from `待实现` to `已实现 ✓`
2. Change `- [ ]` to `- [x]` for newly completed items
3. Add brief implementation note if the feature scope differs from original plan
4. Preserve original checklist item text unless factually incorrect

**Minimal edit principle**:
- Only modify the specific checklist lines that changed
- Don't reformat or rewrite descriptions unless necessary
- Keep list order intact

**Example edit**:
```markdown
# Before (in 待实现):
- [ ] **token_log.json**：每次 LLM 调用后写入一条记录

# After (moved to 已实现):
- [x] **token_log.json**：每次 LLM 调用后写入一条记录，字段：timestamp、command、model、tokens
```

### Step 3: Update README.md Usage

**File**: `README.md`

**Update rules**:
1. Add new command examples if new CLI commands were added
2. Add new flags/options to existing command sections
3. Update behavior descriptions if commands changed
4. Add to "对话内命令" section if chat inline commands were added

**Where to add**:
- CLI commands → Section "CLI 使用"
- Chat commands → Section "对话内命令" table
- New workflows → Appropriate usage section

**Minimal edit principle**:
- Insert new examples near related existing content
- Don't rewrite existing sections unless behavior changed
- Use same style/format as existing examples

**Example addition**:
```markdown
# If adding new --wide flag to ingest
## 摄取资料

# 加载更多 Wiki 上下文（适合 Wiki 已积累大量内容时）
nemsy ingest "/path/to/file.md" --wide
```

### Step 4: Verification Checklist

Before completing, verify:

- [ ] All completed features from commits are checked in MVP
- [ ] No false positives (features marked done that aren't actually complete)
- [ ] README examples match current CLI help text
- [ ] No formatting破坏 (list indentation, code blocks intact)
- [ ] Minimal diff principle followed (only changed what's necessary)

## Common Scenarios

### Scenario 1: Feature Completed

**Commit**: `feat(query): add -a flag for chat inline query archiving`

**Actions**:
1. Find in MVP: `- [ ] **chat 归档（/query -a）**`
2. Mark complete: `- [x]`
3. Add to README chat commands table: `/query <问题> -a`

### Scenario 2: Bug Fix (No Doc Update)

**Commit**: `fix(ingest): handle empty files correctly`

**Actions**:
- MVP: No change (bug fixes don't move checklist items)
- README: Only update if behavior description was wrong

### Scenario 3: Feature Enhanced Beyond Original Plan

**Commit**: `feat(query): ARCHIVABLE now only suggests, doesn't auto-save`

**Actions**:
1. MVP: Update the description in 已实现 to reflect new behavior
2. README: Update usage examples to show explicit --archive requirement

## Anti-Patterns to Avoid

❌ **Don't**: Rewrite entire sections "for clarity"
✅ **Do**: Only edit specific lines that factually changed

❌ **Don't**: Reorganize checklist order
✅ **Do**: Move items between 待实现 and 已实现, preserve order within each

❌ **Don't**: Add speculative future features to README
✅ **Do**: Only document actually implemented and tested features

❌ **Don't**: Remove old information without verifying it's obsolete
✅ **Do**: Update or mark deprecated with clear notices

## Output Format

After completing updates, report:

```
📝 Documentation updated:

MVP.md:
- ✅ Moved 2 items from 待实现 to 已实现
- 📝 Updated description for: query 归档行为

README.md:  
- ➕ Added /query -a example to chat commands
- 📝 Updated query behavior description

Git diff summary: +12 -8 lines
```
