import {
  Button,
  Card,
  Form,
  Input,
  List,
  Space,
  Steps,
  message,
  Typography,
  Tag,
  Alert,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'

import api from '../api'

export default function TakeSurvey() {
  const { token } = useParams()
  const [sp] = useSearchParams()
  const t = token || sp.get('token') || ''
  const [meta, setMeta] = useState(null)
  const [respondentId, setRespondentId] = useState(null)
  const [answers, setAnswers] = useState([])
  const [current, setCurrent] = useState(0)
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const [tokenInput, setTokenInput] = useState('')
  const [invalid, setInvalid] = useState(false)

  const load = async () => {
    try {
      const { data } = await api.get(`/public/surveys/${t}`)
      setMeta(data)
      const r = await api.post('/public/respondents', { link_token: t })
      setRespondentId(r.data.respondent_id)
    } catch (e) {
      print(e)
      setInvalid(true)
      message.error('Invalid or inactive link')
    }
  }

  useEffect(() => {
    setInvalid(false)
    if (t) load()
  }, [t])

  const questions = meta?.questions || []
  const currentQuestion = questions[current]

  const answeredMap = useMemo(() => {
    const map = new Map()
    answers.forEach((a) => map.set(a.question_id, a))
    return map
  }, [answers])

  const currentAnswer = currentQuestion ? answeredMap.get(currentQuestion.id) : null
  const isFlagged = !!currentAnswer?.flagged

  const reloadAnswers = async () => {
    if (!respondentId) return
    const { data } = await api.get(`/public/respondents/${respondentId}/answers`)
    setAnswers(data)
  }
  useEffect(() => {
    reloadAnswers()
  }, [respondentId])

  const save = async (values, flagAction = null) => {
    const existing = answeredMap.get(currentQuestion.id)
    if (existing) {
      const payload = { answer_text: values.answer }
      if (flagAction !== null) payload.flagged = flagAction
      const { data } = await api.put(`/public/answers/${existing.id}`, payload)
      if (data?.low_quality) {
        message.warning(
          'This answer scored low. Consider adding details or aligning with the guideline.',
        )
      }
    } else {
      const payload = {
        respondent_id: respondentId,
        question_id: currentQuestion.id,
        answer_text: values.answer,
      }
      if (flagAction !== null) payload.flagged = flagAction
      const { data } = await api.post('/public/answers', payload)
      if (data?.low_quality) {
        message.warning('This answer scored low. Consider improving it before submitting.')
      }
    }
    await reloadAnswers()
    if (flagAction === true) message.success('Flagged')
    else if (flagAction === false) message.success('Unflagged')
    else message.success('Saved')
  }

  const del = async () => {
    const existing = answeredMap.get(currentQuestion.id)
    if (existing) {
      await api.delete(`/public/answers/${existing.id}`)
      await reloadAnswers()
      form.setFieldValue('answer', '')
    }
  }

  const submitSurvey = async () => {
    await api.post('/public/submit', { respondent_id: respondentId })
    message.success('Submitted. Thank you!')
  }

  useEffect(() => {
    // populate form when moving between questions
    const existing = currentQuestion ? answeredMap.get(currentQuestion.id) : null
    form.setFieldsValue({ answer: existing?.answer_text || '' })
  }, [current, answeredMap, currentQuestion])

  if (!t || invalid) {
    return (
      <Card title="Take Survey" style={{ maxWidth: 560 }}>
        {invalid && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="Invalid or inactive link"
            description="Please paste a valid token below, or ask the admin to regenerate a link."
          />
        )}
        <Input
          placeholder="Paste token here"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value.trim())}
          onPressEnter={() => tokenInput && navigate(`/take/${tokenInput}`)}
        />
        <div style={{ marginTop: 12 }}>
          <Space>
            <Button
              type="primary"
              disabled={!tokenInput}
              onClick={() => navigate(`/take/${tokenInput}`)}
            >
              Take Survey
            </Button>
            <Typography.Text type="secondary">
              This will navigate to /take/&lt;token&gt;
            </Typography.Text>
          </Space>
        </div>
      </Card>
    )
  }

  if (!meta) return <Card loading title="Loading survey..."></Card>
  const linkMeta = meta?.link_meta
  const readOnly = !!linkMeta?.read_only

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>

      <Button onClick={() => navigate(`/take/${t}/chat`)}>Try chat mode</Button>
      <Card title={meta.survey.title}>
        <Typography.Paragraph>{meta.survey.description}</Typography.Paragraph>
        {meta.guideline?.content && (
          <Typography.Paragraph type="secondary">
            <b>Guideline:</b> {meta.guideline.content}
          </Typography.Paragraph>
        )}
      </Card>

      <Card>
        <Steps
          current={current}
          items={questions.map((q) => ({ title: `Q${q.order_index + 1}` }))}
        />
      </Card>

      <Card title={`Question ${current + 1} of ${questions.length}`}>
        <Typography.Paragraph>{currentQuestion?.text}</Typography.Paragraph>
        <Form form={form} layout="vertical" onFinish={(v) => save(v, null)}>
          <Form.Item
            name="answer"
            rules={[{ required: true, message: 'Please enter your answer' }]}
          >
            <Input.TextArea rows={6} placeholder="Type your answer here..." />
          </Form.Item>
          <Space>
            <Button onClick={() => setCurrent(Math.max(0, current - 1))} disabled={current === 0}>
              Previous
            </Button>
            <Button
              onClick={() => setCurrent(Math.min(questions.length - 1, current + 1))}
              disabled={current === questions.length - 1}
            >
              Next
            </Button>
            <Button type="primary" htmlType="submit" disabled={readOnly}>
              Save
            </Button>
            <Button onClick={() => save(form.getFieldsValue(), !isFlagged)} disabled={readOnly}>
              {isFlagged ? 'Unflag' : 'Flag'}
            </Button>
            <Button danger onClick={del} disabled={readOnly}>
              Delete
            </Button>
          </Space>
        </Form>
      </Card>

      <Card title="Your Answers">
        <List
          dataSource={answers.sort((a, b) => a.question_id - b.question_id)}
          renderItem={(a) => {
            const q = questions.find((q) => q.id === a.question_id)
            return (
              <List.Item
                actions={[
                  a.flagged ? <Tag color="red">Flagged</Tag> : null,
                  a.score != null ? <Tag>Score: {a.score.toFixed(2)}</Tag> : null,
                  a.low_quality ? <Tag color="orange">Low Quality</Tag> : null,
                ]}
              >
                <List.Item.Meta
                  title={
                    <b>
                      Q{q?.order_index + 1}: {q?.text}
                    </b>
                  }
                  description={
                    <div>
                      <div style={{ whiteSpace: 'pre-wrap' }}>{a.answer_text}</div>
                      {a.rationale && (
                        <div style={{ marginTop: 8 }}>
                          <Typography.Text strong>Rationale:</Typography.Text>
                          <div
                            style={{
                              whiteSpace: 'pre-wrap',
                              marginTop: 6,
                              color: 'rgba(0,0,0,0.65)',
                            }}
                          >
                            {a.rationale}
                          </div>
                        </div>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )
          }}
        />
        <div style={{ marginTop: 12 }}>
          <Button type="primary" onClick={submitSurvey} disabled={readOnly || answers.length === 0}>
            Submit Survey
          </Button>
        </div>
      </Card>
    </Space>
  )
}
