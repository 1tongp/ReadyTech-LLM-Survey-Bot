import {
  Layout,
  Row,
  Col,
  Card,
  Space,
  Input,
  Select,
  Button,
  Table,
  Typography,
  Drawer,
  Divider,
  List,
  Form,
  message,
  Modal,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'

const { Header, Content } = Layout
import api, { setAdminKey } from '../api'

export default function Admin() {
  const [keyVisible, setKeyVisible] = useState(true)
  const [surveys, setSurveys] = useState([])
  const [detail, setDetail] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [form] = Form.useForm()
  const [filterKeyword, setFilterKeyword] = useState('')
  const [sortOption, setSortOption] = useState('created_desc')

  const load = async () => {
    try {
      const { data } = await api.get('/admin/surveys')
      setSurveys(Array.isArray(data) ? data : [])
      if (selectedId) {
        const res = await api.get(`/admin/surveys/${selectedId}/detail`)
        setDetail(res.data)
      }
    } catch (e) {
      console.error(e)
      message.error('Failed to load surveys. Check your admin key / API.')
    }
  }

  useEffect(() => {
    if (!keyVisible) load()
  }, [keyVisible])
  useEffect(() => {
    if (selectedId) load()
  }, [selectedId])

  // ---- Filter + Sort core (kept minimal) ----
  const displayedSurveys = useMemo(() => {
    const kw = (filterKeyword || '').trim().toLowerCase()
    let list = (surveys || []).slice()

    if (kw) {
      list = list.filter((s) => {
        const title = (s.title || '').toLowerCase()
        const desc = (s.description || '').toLowerCase()
        const status = s.link?.is_active ? 'active' : 'deprecated'
        return title.includes(kw) || desc.includes(kw) || status.includes(kw)
      })
    }

    const cmp = (a, b) => {
      switch (sortOption) {
        case 'title_asc':
          return (a.title || '').localeCompare(b.title || '')
        case 'title_desc':
          return (b.title || '').localeCompare(a.title || '')
        case 'created_asc':
          return new Date(a.created_at || 0) - new Date(b.created_at || 0)
        case 'created_desc':
          return new Date(b.created_at || 0) - new Date(a.created_at || 0)
        case 'status_asc':
          return (b.link?.is_active ? 0 : 1) - (a.link?.is_active ? 0 : 1)
        case 'status_desc':
          return (a.link?.is_active ? 0 : 1) - (b.link?.is_active ? 0 : 1)
        default:
          return 0
      }
    }

    return list.sort(cmp)
  }, [surveys, filterKeyword, sortOption])

  const confirmDeleteSurvey = (row) => {
    Modal.confirm({
      title: `Delete survey “${row.title}”?`,
      content:
        'This will permanently remove the survey, its questions, guidelines, links, and responses. This action cannot be undone.',
      okText: 'Delete',
      okType: 'danger',
      cancelText: 'Cancel',
      onOk: async () => {
        try {
          await api.delete(`/admin/surveys/${row.id}`)
          message.success('Survey deleted')
          await load()
        } catch (e) {
          message.error('Delete failed', e)
        }
      },
    })
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: 'Title', dataIndex: 'title' },
    {
      title: 'Created',
      dataIndex: 'created_at',
      render: (v) => (v ? new Date(v).toLocaleString() : '-'),
      width: 200,
    },
    {
      title: 'Status',
      render: (_, row) => {
        const isOpen = !!row.link?.is_active
        return isOpen ? (
          <span style={{ color: '#389e0d' }}>Open</span>
        ) : (
          <span style={{ color: '#d4380d' }}>Closed</span>
        )
      },
      width: 120,
    },
    {
      title: 'Link Action',
      render: (_, row) => {
        const L = row.link
        if (L?.is_active) {
          return (
            <Button
              danger
              onClick={() => {
                Modal.confirm({
                  title: 'Close this survey?',
                  content: 'Participants will no longer be able to access this survey.',
                  okType: 'danger',
                  onOk: async () => {
                    try {
                      await api.post(`/admin/links/${L.token}/revoke`)
                      message.success('Survey closed')
                      await load()
                    } catch {
                      message.error('Failed to close survey')
                    }
                  },
                })
              }}
            >
              Deprecate
            </Button>
          )
        }
        return (
          <Button
            onClick={async () => {
              try {
                await api.post('/admin/links', { survey_id: row.id })
                message.success('Survey opened')
                await load()
              } catch {
                message.error('Failed to open survey')
              }
            }}
          >
            Re-activate
          </Button>
        )
      },
      width: 160,
    },
    {
      title: 'Actions',
      render: (_, row) => (
        <Space>
          <Button onClick={() => setSelectedId(row.id)}>Open</Button>
          <Button danger onClick={() => confirmDeleteSurvey(row)}>
            Delete
          </Button>
        </Space>
      ),
      width: 160,
    },
  ]

  const createSurvey = async (values) => {
    try {
      const qs = values.questions || []
      const payload = {
        title: values.title,
        description: values.description,
        questions: qs.map((q, i) => ({ text: (q?.text ?? '').trim(), order_index: i })),
      }
      const res = await api.post('/admin/surveys', payload)
      const newId = res.data.id

      const detailRes = await api.get(`/admin/surveys/${newId}/detail`)
      const questionsOrdered = (detailRes.data.questions || []).sort(
        (a, b) => a.order_index - b.order_index,
      )

      await Promise.all(
        questionsOrdered
          .map((q, idx) => {
            const content = (qs[idx]?.guideline || '').trim()
            if (!content) return null
            return api.put(`/admin/questions/${q.id}/guideline`, { content })
          })
          .filter(Boolean),
      )

      message.success('Survey created')

      // Automatically activate a shareable link after creation
      await api.post('/admin/links', { survey_id: newId })
      message.success('Share link activated')
      form.resetFields()
      await load()
    } catch (e) {
      console.error(e)
      message.error('Create failed')
    }
  }

  const createLink = async () => {
    try {
      const { data } = await api.post('/admin/links', { survey_id: selectedId })
      Modal.info({
        title: 'Shareable Link',
        content: (
          <div>
            <p>Token:</p>
            <Typography.Text code copyable>
              {data.token}
            </Typography.Text>
            <p style={{ marginTop: 8 }}>URL (frontend):</p>
            <Typography.Text
              code
              copyable
            >{`${window.location.origin}/take/${data.token}`}</Typography.Text>
            <p style={{ marginTop: 8 }}>
              Status: <b>Active</b>
            </p>
          </div>
        ),
      })
    } catch {
      message.error('Create link failed')
    }
  }

  const exportCsv = () => {
    try {
      const key = api.defaults.headers['X-API-Key']
      const url = `${api.defaults.baseURL}/admin/surveys/${selectedId}/export.csv`
      fetch(url, { headers: { 'X-API-Key': key } }).then(async (r) => {
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `survey_${selectedId}_responses.csv`
        a.click()
      })
    } catch {
      message.error('Export failed')
    }
  }

  if (keyVisible) {
    return (
      <Card title="Enter Admin Key" style={{ maxWidth: 480 }}>
        <Input.Password
          placeholder="Admin Key"
          onPressEnter={(e) => {
            setAdminKey(e.target.value)
            setKeyVisible(false)
          }}
        />
        <div style={{ marginTop: 12 }}>
          <Button
            type="primary"
            onClick={() => {
              const el = document.querySelector('input[type=password]')
              setAdminKey(el?.value || '')
              setKeyVisible(false)
            }}
          >
            Continue
          </Button>
        </div>
      </Card>
    )
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#fafafa' }}>
      <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0' }}>
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Typography.Title level={4} style={{ margin: 0 }}>
            Survey Admin
          </Typography.Title>
        </div>
      </Header>

      <Content style={{ padding: '24px 16px' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto' }}>
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={16}>
              <Card
                title="Surveys"
                extra={
                  <Space>
                    <Input.Search
                      placeholder="Filter by title, description or status"
                      allowClear
                      value={filterKeyword}
                      onChange={(e) => setFilterKeyword(e.target.value)}
                      style={{ width: 280 }}
                    />
                    <Select
                      value={sortOption}
                      onChange={(v) => setSortOption(v)}
                      options={[
                        { value: 'created_desc', label: 'Created (new → old)' },
                        { value: 'created_asc', label: 'Created (old → new)' },
                        { value: 'title_asc', label: 'Title (A → Z)' },
                        { value: 'title_desc', label: 'Title (Z → A)' },
                        { value: 'status_desc', label: 'Status (Active first)' },
                        { value: 'status_asc', label: 'Status (Deprecated first)' },
                      ]}
                      style={{ width: 220 }}
                    />
                    <Button
                      onClick={() => {
                        setFilterKeyword('')
                        setSortOption('created_desc')
                      }}
                    >
                      Reset
                    </Button>
                  </Space>
                }
                bodyStyle={{ paddingTop: 0 }}
              >
                <Table
                  size="middle"
                  rowKey="id"
                  columns={columns}
                  dataSource={displayedSurveys}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                />
              </Card>
            </Col>

            {/* right hand side: Create Survey */}
            <Col xs={24} lg={8}>
              <Card title="Create Survey" bordered>
                <Form layout="vertical" form={form} onFinish={createSurvey}>
                  <Form.Item name="title" label="Title" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="description" label="Description">
                    <Input.TextArea rows={3} />
                  </Form.Item>
                  <Form.List name="questions" initialValue={[{ text: '', guideline: '' }]}>
                    {(fields, { add, remove }) => (
                      <div>
                        <Divider>Questions</Divider>
                        {fields.map((field, idx) => (
                          <div
                            key={field.key}
                            style={{
                              marginBottom: 12,
                              padding: 12,
                              border: '1px solid #f0f0f0',
                              borderRadius: 8,
                            }}
                          >
                            <Form.Item
                              label={`Question #${idx + 1}`}
                              name={[field.name, 'text']}
                              rules={[{ required: true, message: 'Question text required' }]}
                              style={{ marginBottom: 8 }}
                            >
                              <Space.Compact style={{ width: '100%' }}>
                                <Input.TextArea
                                  data-testid="question-field"
                                  placeholder="Enter question text"
                                />
                                <Button onClick={() => remove(field.name)} danger>
                                  Delete
                                </Button>
                              </Space.Compact>
                            </Form.Item>
                            <Form.Item
                              label="Guideline for this question"
                              name={[field.name, 'guideline']}
                            >
                              <Input.TextArea
                                data-testid="guideline-field"
                                rows={3}
                                placeholder="Scoring rubric / hints for this question"
                              />
                            </Form.Item>
                          </div>
                        ))}
                        <Button onClick={() => add({ text: '', guideline: '' })}>
                          Add Question
                        </Button>
                      </div>
                    )}
                  </Form.List>
                  <Divider />
                  <Form.Item>
                    <Button type="primary" htmlType="submit" block>
                      Create
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            </Col>
          </Row>
        </div>
      </Content>

      {/* 详情抽屉：选中某个 Survey 时出现，右侧滑出，不占据主列表空间 */}
      <Drawer
        title={detail ? `Survey #${selectedId}: ${detail.survey.title}` : 'Survey Detail'}
        placement="right"
        width={560}
        open={!!selectedId && !!detail}
        onClose={() => setSelectedId(null)}
        destroyOnClose
        styles={{ body: { paddingBottom: 24 } }}
      >
        {detail && (
          <>
            <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
              {detail.survey.description || 'No description'}
            </Typography.Paragraph>
            <Divider orientation="left">Questions</Divider>
            <List
              dataSource={detail.questions}
              renderItem={(q) => (
                <List.Item style={{ display: 'block' }}>
                  <Space>
                    <Typography.Text strong>#{q.order_index + 1}</Typography.Text>
                    <div>{q.text}</div>
                  </Space>
                  <Input.TextArea
                    rows={3}
                    style={{ marginTop: 8 }}
                    value={q._guidelineDraft ?? q.guideline?.content ?? ''}
                    onChange={(e) => {
                      const val = e.target.value
                      setDetail((prev) => {
                        const copy = { ...prev }
                        copy.questions = prev.questions.map((qq) =>
                          qq.id === q.id ? { ...qq, _guidelineDraft: val } : qq,
                        )
                        return copy
                      })
                    }}
                    placeholder="Write scoring guideline for this question..."
                  />
                  <Space style={{ marginTop: 8 }}>
                    <Button
                      onClick={async () => {
                        const content = (q._guidelineDraft ?? q.guideline?.content ?? '').trim()
                        await api.put(`/admin/questions/${q.id}/guideline`, { content })
                        message.success('Guideline saved')
                        await load()
                      }}
                    >
                      Save Guideline
                    </Button>
                    <Button
                      danger
                      onClick={() => {
                        Modal.confirm({
                          title: 'Delete question?',
                          content: 'This will delete the question and its guideline.',
                          okType: 'danger',
                          onOk: async () => {
                            await api.delete(`/admin/questions/${q.id}/guideline`).catch(() => {})
                            await api.delete(`/admin/questions/${q.id}`)
                            message.success('Question deleted')
                            await load()
                          },
                        })
                      }}
                    >
                      Delete Question
                    </Button>
                  </Space>
                </List.Item>
              )}
            />
            <Divider />
            <Space wrap>
              <Button type="primary" onClick={createLink}>
                Generate Shareable Link
              </Button>
              <Button onClick={exportCsv}>Export CSV</Button>
              <Button onClick={() => setSelectedId(null)}>Close</Button>
            </Space>
          </>
        )}
      </Drawer>
    </Layout>
  )
}
