import json
import os
import time

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
FIRST_GOAL_NAME = '创建今日计划'
FIRST_GOAL_CONTENT = '制定今日行动计划，确定今天要完成的几件事情'

def write(kind, content=None, goal=None):
    row = {'type': kind, 'content': content, 'goal': goal,
           'time': time.strftime('%Y-%m-%d %H:%M:%S')}
    
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 'a',
              encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    
    # print('[log] %s %s %s' % (kind, goal if goal is not None else '', shown[:CUT]),
    #       flush=True)

def humanize_delay(seconds: float) -> str:
    # 四舍五入到整秒，避免 0.3 秒这类小数
    total = int(round(seconds))

    # 负数 / 0 处理（按需改）
    if total <= 0:
        return "现在"
    if total < 60:
        return f"{total}秒后"

    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分")
    if secs:
        parts.append(f"{secs}秒")

    return "".join(parts) + "后执行"

def humanize_desktop_command(command):
    t, v, d = command.get('type'), command.get('value'), command.get('direction')
    dirs = {'UP': '上', 'DOWN': '下', 'LEFT': '左', 'RIGHT': '右'}
    if t == 'keyboard':
        return f"按键 {v}"
    if t == 'mouse':
        return f"鼠标向{dirs.get(d, d)}移动{v}像素"
    if t == 'scroll':
        return f"滚轮向{dirs.get(d, d)}滚动{v}格"
    if t == 'screenshot':
        return "截屏"
    if t == 'clipboard':
        return f"写入剪切板：{v}" if v else "清空剪切板"
    return str(command)

def humanize_leg_command(command):
    # 'done:forward,50,2' → 动词 + 参数
    verb, *args = command.removeprefix('done:').split(',')
    dur = (args[1] if args[1][-1] in 's秒' else args[1] + '秒') if len(args) > 1 else ""
    moves = {'forward': '前进', 'back': '后退', 'left': '原地左转', 'right': '原地右转'}
    if verb in moves:
        return f"{moves[verb]}{dur}（速度{args[0]}%）" if args else moves[verb]
    if verb == 'pan':
        return f"云台水平转到{args[0]}°"
    if verb == 'tilt':
        return f"云台俯仰转到{args[0]}°"
    if verb == 'stop':
        return "电机停止"
    if verb == 'center':
        return "复位（云台回中、电机停）"
    return command

def humanize_atom_action(item):
    q, text = item.get('queue'), item.get('text')
    if q == 'tts':
        return f"说出：{text}"
    if q == 'pub/leg':
        return f"让机器车{humanize_leg_command(text)}"
    if q == 'pub/face':
        return f"把表情换成 {text}"
    if q == 'pub/eye':
        return "让机器车拍一张照"
    if q == '_pub/desktop':
        return f"在电脑上{humanize_desktop_command(item)}"
    if q == '_pub/feishu':
        return "发一张飞书图片" if item.get('img') else f"发飞书消息：{text}"
    if q == '_pub/delay':
        return f"设置延迟提醒「{text}」，{humanize_delay(float(item['in']))}"
    return str(item)

def convert_to_llm_msgs(context):
    """转化为llm消息
    """
    
    llm_msgs = []
    for event in context:
        content = event['content']
        event_time = event['time']
        if event['type'] == 'queue-msg':
            if content['queue'] == 'asr': # event_time
                llm_msgs.append({"role": "user", "content": f"消息时间:{event_time}\n外界声音:{content['text']}"})
            if content['queue'] == '_sub/feishu' and content['type'] == 'text':
                llm_msgs.append({"role": "user", "content": f"消息时间:{event_time}\n飞书消息:{content['text']}"})
            if content['queue'] == '_sub/feishu' and content['type'] == 'image':
                llm_msgs.append({"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": content['data']}}, {"type": "text", "text": f"消息时间:{event_time}\n收到飞书图片如上"}
                ]})
            if content['queue'] == '_sub/delay':
                pub_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(content['due_at'] - content['in']))
                delay_time = humanize_delay(content['in'])
                llm_msgs.append({"role": "user", "content": f"消息时间:{event_time}\n延迟消息:\n发布时间{pub_time}\n延迟时间:{delay_time},已到期\n消息内容:{content['text']}"})
            if content['queue'] == '_sub/desktop' and content['type'] == 'screen':
                llm_msgs.append({"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": content['data']}}, {"type": "text", "text": f"消息时间:{event_time}\n收到电脑桌面截图如上"}
                ]})
            
            if content['queue'] == '_sub/desktop' and content['type'] == 'done':
                llm_msgs.append({"role": "user", "content": f"消息时间:{event_time}\n已完成{humanize_desktop_command(content['command'])}"})
            
            if content['queue'] == 'sub/leg':
                llm_msgs.append({"role":"user", "content": f"消息时间:{event_time}\n已完成{humanize_leg_command(content['text'])}"})

            if content['queue'] == 'sub/eye':
                llm_msgs.append({"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": content['data']}}, {"type": "text", "text": f"消息时间:{event_time}\n收到机器车拍照如上"}
                ]})

        if event['type'] == 'atom-action':
            # LLM 自己当时的输出，翻译成人话回放成 assistant
            lines = [f"{i}. {humanize_atom_action(a)}" for i, a in enumerate(content.get('atom_actions', []), 1)]
            llm_msgs.append({"role": "assistant", "content": f"消息时间:{event_time}\n我执行了以下动作:\n" + "\n".join(lines)})

        if event['type'] == 'check-goal':
            # role = user
            result = '已完成' if content.get('done') else '未完成'
            reason = f"原因:{content['reason']}" if content.get('reason') else ''
            llm_msgs.append({"role": "user", "content": f"消息时间:{event_time}\n目标检查:{result}\n{reason}"})

    return llm_msgs


def read():
    # 每天 至少有一条日志 是今天做什么 什么规划

    # 这里加上
    log_file = os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log')

    if not os.path.exists(log_file):
        first_goal = {
            "type": "create-goal",
            "content":{
                "id": 1,
                "name": FIRST_GOAL_NAME,
                "content": FIRST_GOAL_CONTENT,
                "child-goals": [],
                "father-goal-id": -1,
            },
            "time": time.strftime('%Y-%m-%d %H:%M:%S'), 
            "goal": 1
        }
        
        with open(log_file, 'w') as f:
            f.write(json.dumps(first_goal, ensure_ascii=False) + '\n')
    
    goals = []
    cur_memories = []
    cur_goal = None
    cur_skill = None
    context = []
    with open(os.path.join(LOGS, time.strftime('%Y-%m-%d') + '.log'), 
              encoding='utf-8') as f:
        for line in f:
            event = json.loads(line.strip())
            if event['type'] == 'create-goal':
                cur_memories.clear()
                cur_goal = None
                cur_skill = None
                context = []

                goals.append(event['content'])
                cur_goal = event['content']
                
            if event['type'] == 'retrieve-memory':
                cur_memories = event['content']["memory-ids"]
            
            if event['type'] == 'retrieve-skill':
                cur_skill = event['content']['skill-id']

            if event['type'] in ('queue-msg', 'atom-action', 'check-goal'):
                context.append(event)

    return goals, cur_goal, cur_skill, cur_memories, context
