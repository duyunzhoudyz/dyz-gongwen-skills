# 第 5 步：按违规稿及学段逐条叠加，不改第 4 步实测快照与两份历史基线。
def stage5_expected(filename, mode, stage, expected):
    if stage not in ("义务教育", "高中", "中职"):
        return expected
    additions = {
        ("V_k05_课后服务与收费初稿.txt", "general"): [
            ("K12-G03", "P1", 6), ("K12-G05", "P1", 16), ("K12-G06", "P1", 17)],
        ("V_k05_课后服务与收费初稿.txt", "parents"): [("JZ-006", "P1", 16)],
        ("V_k06_学生资助与关爱排查稿.txt", "general"): [("K12-G04", "P1", n) for n in (7, 9, 10, 11)],
        ("V_k07_寒假致家长信初稿.txt", "parents"): [("JZ-003", "P1", 15), ("JZ-012", "P1", 27)],
        ("V_k09_班主任总结违规稿.txt", "general"): [("K12-G04", "P1", 17)],
    }.get((filename, mode))
    if not additions:
        return expected
    return {"hits": sorted(expected["hits"] + list(map(list, additions)), key=lambda h: (h[2], h[0], h[1]))}
