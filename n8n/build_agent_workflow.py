# -*- coding: utf-8 -*-
"""Sinh workflow n8n của nguyên mẫu AI Agent (mục 3.10 của khóa luận).
python3 build_agent_workflow.py                 -> workflow_ai_agent.json (để import vào n8n)
python3 build_agent_workflow.py --mock cfg.json -> bản thử nghiệm cục bộ (gắn sẵn credential giả, URL cục bộ)
"""
import json, os, sys, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
NS = uuid.UUID('2b7e4c1a-9d3f-4e8a-b1c2-5f6a7b8c9d0e')
SYSTEM = open(os.path.join(HERE, 'chi_dan_he_thong_v1.md'), encoding='utf-8').read().strip()
PHIEN_BAN_CHI_DAN = 'v1.0'
NODES, CONN = [], {}


def nid(name):
    return str(uuid.uuid5(NS, name))


def add(name, typ, ver, params, pos, **extra):
    n = {'parameters': params, 'id': nid(name), 'name': name, 'type': typ, 'typeVersion': ver, 'position': list(pos)}
    n.update(extra)
    NODES.append(n)
    return name


def link(a, b, out=0, kind='main', inp=0):
    lst = CONN.setdefault(a, {}).setdefault(kind, [])
    while len(lst) <= out:
        lst.append([])
    lst[out].append({'node': b, 'type': kind, 'index': inp})


def code(name, js, pos, **extra):
    return add(name, 'n8n-nodes-base.code', 2, {'jsCode': js.strip()}, pos, **extra)


def cond_if(name, left, op, right, pos):
    operator = {'type': 'string', 'operation': 'equals'} if op == 'equals' else {'type': 'boolean', 'operation': 'true', 'singleValue': True}
    c = {'id': nid(name + 'c'), 'leftValue': left, 'rightValue': right, 'operator': operator}
    if op != 'equals':
        c.pop('rightValue')
    return add(name, 'n8n-nodes-base.if', 2.2, {'conditions': {'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose', 'version': 2},
                                                              'conditions': [c], 'combinator': 'and'}, 'looseTypeValidation': True, 'options': {}}, pos)


def setn(name, fields, pos, include_other=False):
    a = [{'id': nid(name + k), 'name': k, 'value': v, 'type': t} for k, v, t in fields]
    p = {'assignments': {'assignments': a}, 'options': {}}
    if include_other:
        p['includeOtherFields'] = True
    return add(name, 'n8n-nodes-base.set', 3.4, p, pos)


def sticky(name, text, pos, w, h, color=None):
    p = {'content': text, 'height': h, 'width': w}
    if color:
        p['color'] = color
    add(name, 'n8n-nodes-base.stickyNote', 1, p, pos)


# ---------------- mô tả công cụ (Bảng 3.16) ----------------
FIELDS = [('tool', 'string'), ('customer_id', 'string'), ('top_k', 'number'), ('risk_group', 'string'), ('filters', 'string'), ('limit', 'number')]
CID = "={{ $fromAI('customer_id', 'Mã CustomerID dạng chuỗi chữ số, chép đúng như người dùng nêu, ví dụ 50123', 'string') }}"
GROUP = "={{ $fromAI('risk_group', 'Nhóm nguy cơ cần xét: thấp, trung bình hoặc cao. Để chuỗi rỗng nếu không giới hạn nhóm', 'string', '') }}"
FILTERS = ("={{ $fromAI('filters', 'Điều kiện lọc dạng chuỗi JSON; để chuỗi rỗng nếu không lọc. Trường so sánh bằng: CityTier (1-3), Complain (0 hoặc 1), "
           "SatisfactionScore (1-5), Gender, MaritalStatus, PreferredLoginDevice, PreferredPaymentMode, PreferedOrderCat. Trường theo khoảng với min và max: "
           "Tenure, DaySinceLastOrder, OrderCount, CashbackAmount, WarehouseToHome, HourSpendOnApp, NumberOfDeviceRegistered, NumberOfAddress, CouponUsed, "
           "OrderAmountHikeFromlastYear. Ví dụ: {\"CityTier\": 3, \"Complain\": 1} hoặc {\"Tenure\": {\"max\": 1} }', 'string', '') }}")
TOOLS = [
    ('get_customer', 'Tra cứu hồ sơ của MỘT khách hàng theo CustomerID trong CRM thử nghiệm: các trường được phép hiển thị và danh sách trường bị thiếu. '
                     'Dùng khi người dùng hỏi thông tin hồ sơ. Trả về status not_found hoặc invalid_id nếu không có mã hoặc mã sai định dạng.',
     {'customer_id': CID}),
    ('predict_risk', 'Tính nguy cơ của MỘT khách hàng theo CustomerID: P(Churn = 1), điểm 1-10, nhóm nguy cơ (thấp 1-2, trung bình 3-5, cao 6-10), '
                     'vị trí so với ngưỡng t*, trường bị thiếu và danh mục lạ. Trả về status not_found hoặc invalid_id nếu không có mã hoặc mã sai định dạng.',
     {'customer_id': CID}),
    ('explain_customer', 'Giải thích dự đoán của MỘT khách hàng theo CustomerID: các yếu tố đóng góp SHAP lớn nhất làm tăng và làm giảm điểm (thang log-odds), '
                         'kèm giá trị của thuộc tính. Không dùng cho tầm quan trọng chung của mô hình.',
     {'customer_id': CID, 'top_k': "={{ $fromAI('top_k', 'Số yếu tố mỗi chiều cần trả về, mặc định 3, tối đa 5', 'number', 3) }}"}),
    ('count_by_group', 'Đếm số khách hàng và tỷ trọng theo ba nhóm nguy cơ trong CRM thử nghiệm, có thể kèm điều kiện lọc. Dùng cho câu hỏi có bao nhiêu, tỷ lệ bao nhiêu.',
     {'risk_group': GROUP, 'filters': FILTERS}),
    ('list_customers', 'Liệt kê các khách hàng có xác suất nguy cơ cao nhất theo thứ tự giảm dần, có thể lọc theo nhóm nguy cơ và điều kiện; tối đa 50 hồ sơ.',
     {'risk_group': GROUP, 'limit': "={{ $fromAI('limit', 'Số khách hàng cần liệt kê, mặc định 10, tối đa 50', 'number', 10) }}", 'filters': FILTERS}),
]

JS_HOAN_THIEN = r"""
// Chuẩn hóa phản hồi cuối: lỗi mô hình ngôn ngữ hoặc chạm giới hạn số vòng được báo rõ (Bảng 3.18); giữ bước trung gian để kiểm thử.
const a = $input.first().json || {};
const vao = $('Chuẩn hóa đầu vào').first().json;
// Phiên bản chỉ dẫn hệ thống đọc từ dòng đầu của System Message trong node AI Agent (một nguồn duy nhất).
const phienBan = () => { try { const sm = String((($('AI Agent').params || {}).options || {}).systemMessage || ''); return (sm.match(/phiên bản\s+(v[\w.]+)/i) || [])[1] || 'không rõ'; } catch (e) { return 'không rõ'; } };
let output = typeof a.output === 'string' ? a.output : '';
let trang_thai = 'ok';
if (a.error) {
  trang_thai = 'loi_agent';
  output = 'Xin lỗi, hệ thống chưa xử lý được yêu cầu do lỗi kỹ thuật khi gọi mô hình ngôn ngữ. Vui lòng thử lại sau.';
} else if (/stopped due to max iterations|max iterations/i.test(output)) {
  trang_thai = 'cham_gioi_han_vong';
  output = 'Chưa hoàn thành yêu cầu vì đã chạm giới hạn số bước xử lý. Vui lòng tách yêu cầu thành các câu hỏi nhỏ hơn.';
} else if (!output.trim()) {
  trang_thai = 'rong';
  output = 'Xin lỗi, hệ thống chưa tạo được phản hồi cho yêu cầu này. Vui lòng thử lại.';
}
const buoc = (a.intermediateSteps || []).map(s => ({ tool: s.action ? s.action.tool : '', input: s.action ? s.action.toolInput : null, observation: s.observation }));
return [{ json: { output, trang_thai, nguon: vao.nguon, sessionId: vao.sessionId, intermediateSteps: buoc,
  loi: a.error ? String(typeof a.error === 'string' ? a.error : JSON.stringify(a.error)).slice(0, 500) : '',
  phien_ban_chi_dan: phienBan(), executionId: $execution.id } }];
"""

JS_KIEM_TRA = r"""
// Kiểm tra tham số ở n8n trước khi gọi dịch vụ: chỉ năm công cụ chỉ-đọc, chỉ gửi đúng tham số của từng công cụ.
const x = $input.first().json;
const THAM_SO = { get_customer: ['customer_id'], predict_risk: ['customer_id'], explain_customer: ['customer_id', 'top_k'],
  count_by_group: ['risk_group', 'filters'], list_customers: ['risk_group', 'limit', 'filters'] };
const url = String(x.dich_vu_url || '').trim().replace(/\/+$/, '');
const tra = (status, message) => [{ json: { bo_qua_goi: true, tool: x.tool, ket_qua: { status, tool: x.tool, message } } }];
if (!THAM_SO[x.tool]) return tra('invalid_input', 'Công cụ không hợp lệ: ' + x.tool);
if (!/^https?:\/\/[^<>\s]+$/.test(url)) return tra('service_error', 'Chưa cấu hình địa chỉ dịch vụ dự đoán (dich_vu_url) ở node "Cấu hình dịch vụ (điền tại đây)".');
const body = {};
for (const k of THAM_SO[x.tool]) { const v = x[k]; if (v !== undefined && v !== null && String(v).trim() !== '') body[k] = v; }
if (typeof body.filters === 'string') {
  const s = body.filters.trim();
  if (s === '{}' || s === 'null') delete body.filters;
  else { try { body.filters = JSON.parse(s); } catch (e) { return tra('invalid_input', 'filters phải là JSON hợp lệ, ví dụ {"CityTier": 3}.'); } }
}
return [{ json: { bo_qua_goi: false, tool: x.tool, url: url + '/tools/' + x.tool, body, thoi_gian_cho_ms: Number(x.thoi_gian_cho_ms) || 60000 } }];
"""

JS_RUT_GON = r"""
// Trả kết quả gọn cho Agent; lỗi kết nối hoặc quá thời gian (sau khi đã thử lại một lần) thành status = service_error.
const it = $input.first().json || {};
const req = $('Kiểm tra tham số công cụ').first().json;
let out;
if (req.bo_qua_goi) out = req.ket_qua;
else if (it.error) {
  const e = it.error; const msg = typeof e === 'string' ? e : (e.message || JSON.stringify(e));
  out = { status: 'service_error', tool: req.tool, message: 'Không gọi được dịch vụ dự đoán sau 2 lần thử: ' + String(msg).slice(0, 200) };
} else out = it;
if (out && out.field_descriptions && req.tool !== 'get_customer') delete out.field_descriptions;
return [{ json: out }];
"""


def build(mock=None):
    NODES.clear(); CONN.clear()
    mock = mock or {}
    cred = mock.get('credentials', {})
    # ----- Lớp giao tiếp -----
    chat_params = {'public': True, 'mode': 'hostedChat', 'options': {}} if mock.get('chat_public') else {'options': {}}
    add('Khi có tin nhắn chat', '@n8n/n8n-nodes-langchain.chatTrigger', 1.1, chat_params, (0, 0), webhookId=nid('chat-webhook'))
    wh = {'httpMethod': 'POST', 'path': 'kltn-agent-kiem-thu', 'authentication': 'headerAuth', 'responseMode': 'responseNode', 'options': {}}
    add('Webhook kiểm thử', 'n8n-nodes-base.webhook', 2, wh, (0, 220), webhookId=nid('test-webhook'),
        **({'credentials': {'httpHeaderAuth': cred['webhook']}} if 'webhook' in cred else {}))
    setn('Chuẩn hóa đầu vào', [
        ('chatInput', "={{ $json.chatInput ?? ($json.body ? $json.body.chatInput : '') ?? '' }}", 'string'),
        ('sessionId', "={{ $json.sessionId ?? ($json.body && $json.body.sessionId ? $json.body.sessionId : $execution.id) }}", 'string'),
        ('nguon', "={{ $json.body !== undefined ? 'kiem_thu' : 'chat' }}", 'string')], (240, 100))
    link('Khi có tin nhắn chat', 'Chuẩn hóa đầu vào'); link('Webhook kiểm thử', 'Chuẩn hóa đầu vào')
    # ----- Lớp điều phối -----
    add('AI Agent', '@n8n/n8n-nodes-langchain.agent', 2.2, {
        'promptType': 'define', 'text': '={{ $json.chatInput }}', 'hasOutputParser': False,
        'options': {'systemMessage': SYSTEM, 'maxIterations': 6, 'returnIntermediateSteps': True, 'enableStreaming': False}},
        (520, 100), onError='continueRegularOutput')
    add('OpenAI Chat Model', '@n8n/n8n-nodes-langchain.lmChatOpenAi', 1.2, {
        'model': {'__rl': True, 'mode': 'id', 'value': mock.get('model', 'gpt-4.1')},
        'options': {'temperature': 0, 'maxTokens': 2000, 'timeout': 120000, 'maxRetries': 2}}, (380, 360),
        **({'credentials': {'openAiApi': cred['openai']}} if 'openai' in cred else {}))
    add('Bộ nhớ hội thoại', '@n8n/n8n-nodes-langchain.memoryBufferWindow', 1.3, {
        'sessionIdType': 'customKey', 'sessionKey': '={{ $json.sessionId }}', 'contextWindowLength': 6}, (520, 360))
    link('OpenAI Chat Model', 'AI Agent', kind='ai_languageModel'); link('Bộ nhớ hội thoại', 'AI Agent', kind='ai_memory')
    link('Chuẩn hóa đầu vào', 'AI Agent')
    for i, (tname, desc, values) in enumerate(TOOLS):
        schema = []
        for f, t in FIELDS:
            used = f == 'tool' or f in values
            schema.append({'id': f, 'displayName': f, 'required': False, 'defaultMatch': False, 'display': True,
                           'canBeUsedToMatch': True, 'type': t, 'removed': not used})
        v = {'tool': tname}
        v.update(values)
        add(tname, '@n8n/n8n-nodes-langchain.toolWorkflow', 2.2, {
            'description': desc, 'source': 'database',
            'workflowId': {'__rl': True, 'mode': 'id', 'value': '={{ $workflow.id }}'},
            'workflowInputs': {'mappingMode': 'defineBelow', 'value': v, 'matchingColumns': [], 'schema': schema,
                               'attemptToConvertTypes': False, 'convertFieldsToString': False}}, (660 + 140 * i, 360))
        link(tname, 'AI Agent', kind='ai_tool')
    code('Hoàn thiện phản hồi', JS_HOAN_THIEN, (880, 100))
    link('AI Agent', 'Hoàn thiện phản hồi')
    cond_if('Là lượt kiểm thử?', '={{ $json.nguon }}', 'equals', 'kiem_thu', (1100, 100))
    link('Hoàn thiện phản hồi', 'Là lượt kiểm thử?')
    add('Trả kết quả kiểm thử', 'n8n-nodes-base.respondToWebhook', 1.1, {'respondWith': 'firstIncomingItem', 'options': {}}, (1320, 20))
    link('Là lượt kiểm thử?', 'Trả kết quả kiểm thử', 0)
    # ----- Lớp công cụ: quy trình con dùng chung cho năm công cụ -----
    y = 760
    add('Khi Agent gọi công cụ', 'n8n-nodes-base.executeWorkflowTrigger', 1.1, {
        'inputSource': 'workflowInputs', 'workflowInputs': {'values': [{'name': f, 'type': t} for f, t in FIELDS]}}, (0, y))
    setn('Cấu hình dịch vụ (điền tại đây)', [
        ('dich_vu_url', mock.get('service_url', 'https://TEN-TAI-KHOAN-TEN-SPACE.hf.space'), 'string'),
        ('thoi_gian_cho_ms', 60000, 'number')], (240, y), include_other=True)
    code('Kiểm tra tham số công cụ', JS_KIEM_TRA, (480, y))
    cond_if('Cần gọi dịch vụ?', '={{ !$json.bo_qua_goi }}', 'true', None, (700, y))
    add('Gọi dịch vụ dự đoán', 'n8n-nodes-base.httpRequest', 4.2, {
        'method': 'POST', 'url': '={{ $json.url }}', 'authentication': 'genericCredentialType', 'genericAuthType': 'httpHeaderAuth',
        'sendBody': True, 'specifyBody': 'json', 'jsonBody': '={{ JSON.stringify($json.body) }}',
        'options': {'timeout': '={{ $json.thoi_gian_cho_ms }}'}}, (920, y - 80),
        retryOnFail=True, maxTries=2, waitBetweenTries=1000, onError='continueRegularOutput',
        **({'credentials': {'httpHeaderAuth': cred['service']}} if 'service' in cred else {}))
    code('Rút gọn kết quả cho Agent', JS_RUT_GON, (1140, y))
    for a, b, o in [('Khi Agent gọi công cụ', 'Cấu hình dịch vụ (điền tại đây)', 0), ('Cấu hình dịch vụ (điền tại đây)', 'Kiểm tra tham số công cụ', 0),
                    ('Kiểm tra tham số công cụ', 'Cần gọi dịch vụ?', 0), ('Cần gọi dịch vụ?', 'Gọi dịch vụ dự đoán', 0),
                    ('Cần gọi dịch vụ?', 'Rút gọn kết quả cho Agent', 1), ('Gọi dịch vụ dự đoán', 'Rút gọn kết quả cho Agent', 0)]:
        link(a, b, o)
    # ----- Ghi chú -----
    sticky('Ghi chú: Agent', (
        '## Nguyên mẫu AI Agent đánh giá nguy cơ rời bỏ (mục 3.10)\n'
        '- Chat: bấm **Open chat**. Kiểm thử tự động: POST tới **Webhook kiểm thử** (header xác thực).\n'
        '- **AI Agent** (Tools Agent): chỉ dẫn hệ thống ' + PHIEN_BAN_CHI_DAN + ', Max Iterations 6, trả bước trung gian, tắt streaming.\n'
        '- Năm công cụ gọi lại **chính workflow này** qua node *Khi Agent gọi công cụ* → dịch vụ dự đoán Python.\n'
        '- Lưu workflow trước khi chat: công cụ chạy bản đã lưu.'), (-40, -330), 660, 300, 5)
    sticky('Ghi chú: công cụ', (
        '### Quy trình con của các công cụ\nĐiền `dich_vu_url` (địa chỉ Space, không có dấu / ở cuối). '
        'Node **Gọi dịch vụ dự đoán** dùng credential *Header Auth* với tên header `X-API-Key`. '
        'Lỗi kết nối được thử lại 1 lần rồi trả `service_error` cho Agent.'), (-40, y - 260), 660, 200, 4)
    wf = {'name': 'KLTN – AI Agent đánh giá nguy cơ rời bỏ' + (' (MOCK)' if mock else ''), 'nodes': NODES, 'connections': CONN, 'pinData': {},
          'settings': {'executionOrder': 'v1', 'timezone': 'Asia/Ho_Chi_Minh', 'callerPolicy': 'workflowsFromSameOwner', 'saveManualExecutions': True},
          'active': False, 'meta': {'templateCredsSetupCompleted': False}, 'tags': []}
    if mock.get('wf_id'):
        wf['id'] = mock['wf_id']
    return wf


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--mock':
        m = json.load(open(sys.argv[2], encoding='utf-8'))
        wf, out = build(m), m['out']
    else:
        wf, out = build(), os.path.join(HERE, 'workflow_ai_agent.json')
    json.dump(wf, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('wrote', out, len(wf['nodes']), 'nodes', os.path.getsize(out), 'bytes')
