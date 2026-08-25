/**
 * 简单的 API 服务器中间件
 * 替代 vite.config.ts 中的 bypass 函数
 */

import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DATA_DIR = path.resolve(__dirname, '../data');
const PAPERS_DIR = path.join(DATA_DIR, 'papers');
const CRON_JOBS_FILE = path.join(DATA_DIR, 'cron_jobs.json');

// 确保目录存在
if (!fs.existsSync(PAPERS_DIR)) {
  fs.mkdirSync(PAPERS_DIR, { recursive: true });
}
if (!fs.existsSync(path.join(PAPERS_DIR, 'pdfs'))) {
  fs.mkdirSync(path.join(PAPERS_DIR, 'pdfs'), { recursive: true });
}

// 读取Cron任务
function loadCronJobs() {
  try {
    if (fs.existsSync(CRON_JOBS_FILE)) {
      return JSON.parse(fs.readFileSync(CRON_JOBS_FILE, 'utf-8'));
    }
  } catch (error) {
    console.error('Error loading cron jobs:', error);
  }
  return { jobs: [] };
}

// 保存Cron任务
function saveCronJobs(data) {
  fs.writeFileSync(CRON_JOBS_FILE, JSON.stringify(data, null, 2));
}

// 执行命令并返回Promise
function execCommand(command, args, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      env: { ...process.env, DATA_DIR }
    });

    let output = '';
    let errorOutput = '';
    let resolved = false;

    const timer = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        child.kill();
        reject(new Error('Timeout'));
      }
    }, timeout);

    child.stdout.on('data', (data) => {
      output += data.toString();
    });

    child.stderr.on('data', (data) => {
      errorOutput += data.toString();
    });

    child.on('close', (code) => {
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);
        if (code === 0) {
          try {
            resolve(JSON.parse(output));
          } catch (e) {
            resolve({ success: true, data: output.trim() });
          }
        } else {
          reject(new Error(errorOutput || 'Command failed'));
        }
      }
    });

    child.on('error', (error) => {
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);
        reject(error);
      }
    });
  });
}

// 解析请求体的辅助函数
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString();
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(body));
      } catch {
        resolve({});
      }
    });
    req.on('error', reject);
  });
}

// API 处理函数
async function handleAPI(req, res) {
  const url = req.url || '';
  
  // 设置CORS头
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  
  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return true;
  }

  try {
    // ==================== Chat API ====================
    
    // 聊天完成（非流式）
    if (url === '/api/chat/completions' && req.method === 'POST') {
      const body = await parseBody(req);
      const { messages } = body;
      
      if (!messages || !Array.isArray(messages)) {
        res.writeHead(400);
        res.end(JSON.stringify({ success: false, error: 'Messages array required' }));
        return true;
      }
      
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/chat_agent.py'),
        'chat',
        JSON.stringify(messages)
      ], 120000);
      
      res.setHeader('Content-Type', 'application/json');
      res.writeHead(200);
      res.end(JSON.stringify({ success: true, response: result.data || result }));
      return true;
    }
    
    // 聊天完成（流式）
    if (url === '/api/chat/completions/stream' && req.method === 'POST') {
      const body = await parseBody(req);
      const { messages } = body;
      
      if (!messages || !Array.isArray(messages)) {
        res.writeHead(400);
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ success: false, error: 'Messages array required' }));
        return true;
      }
      
      // 设置 SSE 响应头
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');
      res.writeHead(200);
      
      // 启动 Python 子进程进行流式调用
      const scriptPath = path.resolve(__dirname, '../scripts/chat_agent_stream.py');
      const child = spawn('python', [
        scriptPath,
        JSON.stringify(messages)
      ], {
        env: { ...process.env, DATA_DIR }
      });
      
      let buffer = '';
      
      child.stdout.on('data', (data) => {
        buffer += data.toString();
        const lines = buffer.split('\n');
        buffer = lines.pop(); // 保留未完成的行
        
        for (const line of lines) {
          if (line.trim()) {
            res.write(`data: ${line}\n\n`);
          }
        }
      });
      
      child.stderr.on('data', (data) => {
        console.error('Chat stream error:', data.toString());
      });
      
      child.on('close', (code) => {
        if (buffer.trim()) {
          res.write(`data: ${buffer}\n\n`);
        }
        res.write('data: [DONE]\n\n');
        res.end();
      });
      
      child.on('error', (error) => {
        console.error('Chat process error:', error);
        res.write(`data: [ERROR] ${error.message}\n\n`);
        res.end();
      });
      
      return true;
    }
    
    // ==================== 对话 API ====================
    
    // 获取对话列表
    if (url === '/api/conversations' && req.method === 'GET') {
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'list_conversations'
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 获取单个对话详情
    const getConversationMatch = url.match(/^\/api\/conversations\/([^\/]+)$/);
    if (getConversationMatch && req.method === 'GET') {
      const id = getConversationMatch[1];
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'get_conversation',
        JSON.stringify({ conversationId: id })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 创建对话
    if (url === '/api/conversations' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'create_conversation',
        JSON.stringify(body)
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 更新对话
    if (getConversationMatch && req.method === 'PUT') {
      const id = getConversationMatch[1];
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'update_conversation',
        JSON.stringify({ conversationId: id, updates: body })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 删除对话
    if (getConversationMatch && req.method === 'DELETE') {
      const id = getConversationMatch[1];
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'delete_conversation',
        JSON.stringify({ conversationId: id })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 添加消息到对话
    const addMessageMatch = url.match(/^\/api\/conversations\/([^\/]+)\/messages$/);
    if (addMessageMatch && req.method === 'POST') {
      const conversationId = addMessageMatch[1];
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'add_chat_message',
        JSON.stringify({ ...body, conversationId })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // ==================== 全局搜索 API ====================
    
    // 全局搜索
    if (url === '/api/search' && req.method === 'GET') {
      const urlObj = new URL(url, 'http://localhost');
      const query = urlObj.searchParams.get('q') || '';
      const limit = parseInt(urlObj.searchParams.get('limit') || '20');
      
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'global_search',
        JSON.stringify({ query, limit })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // ==================== 原有 API ====================
    
    // 1. 获取论文列表
    if (url === '/api/papers' && req.method === 'GET') {
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/fetch_arxiv.py'),
        'list',
        '--limit', '100'
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }

    // 2. 抓取论文
    if (url.startsWith('/api/papers/fetch') && req.method === 'POST') {
      const urlObj = new URL(url, 'http://localhost');
      const max = urlObj.searchParams.get('max') || '10';
      const keywords = urlObj.searchParams.get('keywords') || '';
      
      const args = ['fetch', '--max', max];
      if (keywords) {
        args.push('--keywords', keywords);
      }
      
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/fetch_arxiv.py'),
        ...args
      ], 60000);
      
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }

    // 3. 删除论文
    const deleteMatch = url.match(/^\/api\/papers\/([^\/]+)$/);
    if (deleteMatch && req.method === 'DELETE') {
      const id = deleteMatch[1];
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'delete_paper',
        JSON.stringify({ paper_id: id })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }

    // 4. 下载PDF
    const downloadMatch = url.match(/^\/api\/papers\/([^\/]+)\/download$/);
    if (downloadMatch && req.method === 'POST') {
      const arxivId = downloadMatch[1];
      const pdfUrl = `https://arxiv.org/pdf/${arxivId}.pdf`;
      const pdfPath = path.join(PAPERS_DIR, 'pdfs', `${arxivId}.pdf`);
      
      await execCommand('curl', ['-L', '-o', pdfPath, pdfUrl], 60000);
      
      res.writeHead(200);
      res.end(JSON.stringify({ success: true, path: pdfPath }));
      return true;
    }

    // 5. 生成论文总结
    const summarizeMatch = url.match(/^\/api\/papers\/([^\/]+)\/summarize$/);
    if (summarizeMatch && req.method === 'POST') {
      const paperId = summarizeMatch[1];
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/summarize_paper.py'),
        paperId
      ], 120000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }

    // 6. 获取Cron任务列表
    if (url === '/api/cron/jobs' && req.method === 'GET') {
      const data = loadCronJobs();
      res.writeHead(200);
      res.end(JSON.stringify(data));
      return true;
    }

    // 7. 创建Cron任务
    if (url === '/api/cron/jobs' && req.method === 'POST') {
      let body = '';
      req.on('data', (chunk) => {
        body += chunk.toString();
      });
      req.on('end', () => {
        try {
          const jobData = JSON.parse(body);
          const data = loadCronJobs();
          const newJob = {
            id: Date.now().toString(),
            ...jobData,
            enabled: true,
            runCount: 0,
            createdAt: Date.now(),
          };
          data.jobs.push(newJob);
          saveCronJobs(data);
          res.writeHead(200);
          res.end(JSON.stringify({ success: true, job: newJob }));
        } catch (error) {
          res.writeHead(400);
          res.end(JSON.stringify({ success: false, message: 'Invalid data' }));
        }
      });
      return true;
    }

    // 8. 切换Cron任务状态
    const toggleMatch = url.match(/^\/api\/cron\/jobs\/([^\/]+)\/toggle$/);
    if (toggleMatch && req.method === 'POST') {
      const id = toggleMatch[1];
      const data = loadCronJobs();
      const job = data.jobs.find((j) => j.id === id);
      if (job) {
        job.enabled = !job.enabled;
        saveCronJobs(data);
        res.writeHead(200);
        res.end(JSON.stringify({ success: true }));
      } else {
        res.writeHead(404);
        res.end(JSON.stringify({ success: false, message: 'Job not found' }));
      }
      return true;
    }

    // 9. 立即运行Cron任务
    const runMatch = url.match(/^\/api\/cron\/jobs\/([^\/]+)\/run$/);
    if (runMatch && req.method === 'POST') {
      const id = runMatch[1];
      const data = loadCronJobs();
      const job = data.jobs.find((j) => j.id === id);
      if (job) {
        // 异步执行命令
        const cmd = job.command.split(' ');
        const scriptPath = path.resolve(__dirname, '..', cmd[1]);
        spawn('python', [scriptPath, ...cmd.slice(2)], {
          env: { ...process.env, DATA_DIR },
          detached: true
        });
        
        job.runCount++;
        job.lastRun = Date.now();
        saveCronJobs(data);
        res.writeHead(200);
        res.end(JSON.stringify({ success: true }));
      } else {
        res.writeHead(404);
        res.end(JSON.stringify({ success: false, message: 'Job not found' }));
      }
      return true;
    }

    // 10. 删除Cron任务
    const deleteCronMatch = url.match(/^\/api\/cron\/jobs\/([^\/]+)$/);
    if (deleteCronMatch && req.method === 'DELETE') {
      const id = deleteCronMatch[1];
      const data = loadCronJobs();
      data.jobs = data.jobs.filter((j) => j.id !== id);
      saveCronJobs(data);
      res.writeHead(200);
      res.end(JSON.stringify({ success: true }));
      return true;
    }

    // ==================== Agent 多Agent协作 API ====================
    
    // 创建 Agent Session
    if (url === '/api/agent/sessions' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'create_agent_session',
        JSON.stringify(body)
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 获取 Agent Sessions
    if (url === '/api/agent/sessions' && req.method === 'GET') {
      const urlObj = new URL(url, 'http://localhost');
      const projectId = urlObj.searchParams.get('projectId');
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'get_agent_sessions',
        JSON.stringify({ projectId })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 更新 Agent Session
    const updateAgentSessionMatch = url.match(/^\/api\/agent\/sessions\/([^\/]+)$/);
    if (updateAgentSessionMatch && req.method === 'PUT') {
      const id = updateAgentSessionMatch[1];
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'update_agent_session',
        JSON.stringify({ sessionId: id, updates: body })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 添加 Agent Message
    const agentMessagesMatch = url.match(/^\/api\/agent\/sessions\/([^\/]+)\/messages$/);
    if (agentMessagesMatch && req.method === 'POST') {
      const sessionId = agentMessagesMatch[1];
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'add_agent_message',
        JSON.stringify({ ...body, sessionId })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 获取 Agent Messages
    if (agentMessagesMatch && req.method === 'GET') {
      const sessionId = agentMessagesMatch[1];
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'get_agent_messages',
        JSON.stringify({ sessionId })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 运行 Agent 工作流 (SSE 流式输出)
    if (url === '/api/agent/run' && req.method === 'POST') {
      const body = await parseBody(req);
      const { requirement, workflow } = body;
      
      // 设置 SSE 响应头
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');
      res.writeHead(200);
      
      // 运行 Agent 服务
      const scriptPath = path.resolve(__dirname, '../scripts/agent_service.py');
      const workflowType = workflow || 'workflow';
      
      const child = spawn('python', [
        scriptPath,
        workflowType,
        requirement || ''
      ], {
        env: { ...process.env }
      });
      
      let buffer = '';
      
      child.stdout.on('data', (data) => {
        buffer += data.toString();
        const lines = buffer.split('\n');
        buffer = lines.pop();
        
        for (const line of lines) {
          if (line.trim()) {
            res.write(`data: ${line}\n\n`);
          }
        }
      });
      
      child.stderr.on('data', (data) => {
        console.error('Agent service error:', data.toString());
      });
      
      child.on('close', (code) => {
        if (buffer.trim()) {
          res.write(`data: ${buffer}\n\n`);
        }
        res.write('data: [DONE]\n\n');
        res.end();
      });
      
      return true;
    }

    // ==================== Formula OCR API ====================
    
    // 识别公式
    if (url === '/api/formula/recognize' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'recognize_formula',
        JSON.stringify(body)
      ], 30000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 获取公式识别历史
    if (url === '/api/formula/history' && req.method === 'GET') {
      const urlObj = new URL(url, 'http://localhost');
      const limit = parseInt(urlObj.searchParams.get('limit') || '100');
      const offset = parseInt(urlObj.searchParams.get('offset') || '0');
      const favoritesOnly = urlObj.searchParams.get('favorites') === 'true';
      
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'get_formula_history',
        JSON.stringify({ limit, offset, favoritesOnly })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 更新公式记录
    if (url === '/api/formula/history' && req.method === 'PUT') {
      const body = await parseBody(req);
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'update_formula_record',
        JSON.stringify(body)
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 删除公式记录
    const deleteFormulaMatch = url.match(/^\/api\/formula\/history\/([^\/]+)$/);
    if (deleteFormulaMatch && req.method === 'DELETE') {
      const id = deleteFormulaMatch[1];
      
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'delete_formula_record',
        JSON.stringify({ recordId: id })
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }
    
    // 获取公式统计
    if (url === '/api/formula/stats' && req.method === 'GET') {
      const result = await execCommand('python', [
        path.resolve(__dirname, '../scripts/db_api.py'),
        'get_formula_stats'
      ], 10000);
      res.writeHead(200);
      res.end(JSON.stringify(result));
      return true;
    }

    return false;
  } catch (error) {
    console.error('API Error:', error);
    res.writeHead(500);
    res.end(JSON.stringify({ success: false, message: error.message }));
    return true;
  }
}

export { handleAPI };
