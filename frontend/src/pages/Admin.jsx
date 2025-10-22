import React, { useEffect, useMemo, useState } from 'react'
import { Button, Card, Form, Input, Space, Table, message, Modal, List, Typography, Divider } from 'antd'
import api, { setAdminKey } from '../api'

export default function Admin(){
  const [keyVisible, setKeyVisible] = useState(true)
  const [surveys, setSurveys] = useState([])
  const [detail, setDetail] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [form] = Form.useForm()
  const [qForm] = Form.useForm()

  const load = async()=>{
    const {data} = await api.get('/admin/surveys')
    setSurveys(data)
    if (selectedId){
      const res = await api.get(`/admin/surveys/${selectedId}/detail`)
      setDetail(res.data)
    }
  }

  useEffect(()=>{ if(!keyVisible) load() },[keyVisible])
  useEffect(()=>{ if(selectedId){ load() } },[selectedId])

  const columns = [
    {title:'ID', dataIndex:'id', width:60},
    {title:'Title', dataIndex:'title'},
    {title:'Created', dataIndex:'created_at'},
    {title:'Actions', render:(_,row)=> <Space>
        <Button onClick={()=>setSelectedId(row.id)}>Open</Button>
        <Button danger onClick={async()=>{ await api.delete(`/admin/surveys/${row.id}`); message.success('Deleted'); load();}}>Delete</Button>
      </Space>}
  ]

  const createSurvey = async (values) => {
    // values.questions formate is [{text, guideline}, ...]
    const qs = values.questions || [];

    // 1) Create survey without guideline
    const payload = {
      title: values.title,
      description: values.description,
      questions: qs.map((q, i) => ({ text: (q?.text ?? '').trim(), order_index: i }))
    };

    const res = await api.post('/admin/surveys', payload);
    const newId = res.data.id;

    // 2) Fetch questions to get their IDs
    const detailRes = await api.get(`/admin/surveys/${newId}/detail`);
    const questionsOrdered = (detailRes.data.questions || []).sort((a, b) => a.order_index - b.order_index);

    // 3) Update guidelines per question
    await Promise.all(
      questionsOrdered.map((q, idx) => {
        const content = (qs[idx]?.guideline || '').trim();
        if (!content) return null;
        return api.put(`/admin/questions/${q.id}/guideline`, { content });
      }).filter(Boolean)
    );

    message.success('Survey created');
    form.resetFields();
    await load();
  };

  const addQuestion = async(values)=>{
    await api.post(`/admin/surveys/${selectedId}/questions`, {text:values.text, order_index: (detail?.questions?.length||0)})
    qForm.resetFields(); await load()
  }

  const createLink = async()=>{
    const {data} = await api.post('/admin/links', {survey_id:selectedId})
    Modal.info({title:'Shareable Link', content:(
      <div>
      <p>Token:</p>
      <Typography.Text code copyable>{data.token}</Typography.Text>
      <p>URL (frontend):</p>
      <Typography.Text code copyable>{`${window.location.origin}/take/${data.token}`}</Typography.Text>
      </div>
    )})
  }

  const exportCsv = ()=>{
    const key = api.defaults.headers['X-API-Key']
    const url = `${api.defaults.baseURL}/admin/surveys/${selectedId}/export.csv`
    fetch(url, { headers: {'X-API-Key': key}}).then(async r=>{
      const blob = await r.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `survey_${selectedId}_responses.csv`
      a.click()
    })
  }

  if (keyVisible){
    return <Card title="Enter Admin Key" style={{maxWidth:480}}>
      <Input.Password placeholder="Admin Key" onPressEnter={(e)=>{
        setAdminKey(e.target.value); setKeyVisible(false)
      }}/>
      <div style={{marginTop:12}}>
        <Button type="primary" onClick={()=>{
          const el = document.querySelector('input[type=password]')
          setAdminKey(el.value); setKeyVisible(false)
        }}>Continue</Button>
      </div>
    </Card>
  }

  return (
    <Space align="start" size="large" wrap>
      <Card title="Create Survey" style={{width:420}}>
        <Form layout="vertical" form={form} onFinish={createSurvey}>
          <Form.Item name="title" label="Title" rules={[{required:true}]}>
            <Input/>
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={3}/>
          </Form.Item>
          <Form.List name="questions" initialValue={[{ text: '', guideline: '' }]}>
            {(fields, { add, remove }) => (
              <div>
                <Divider>Questions</Divider>
                {fields.map((field, idx) => (
                  <div key={field.key} style={{ marginBottom: 12, padding: 12, border: '1px solid #f0f0f0', borderRadius: 8 }}>
                    <Space align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                      <Form.Item
                        label={`Question #${idx + 1}`}
                        name={[field.name, 'text']}
                        rules={[{ required: true, message: 'Question text required' }]}
                        style={{ flex: 1 }}
                      >
                        <Space>
                        <Input.TextArea data-testid="question-field" placeholder="Enter question text" />                     
                        <Button onClick={() => remove(field.name)} danger>Delete</Button>
                        </Space>
                      </Form.Item>
                    </Space>
                    <Form.Item
                      label="Guideline for this question"
                      name={[field.name, 'guideline']}
                    >
                      <Input.TextArea data-testid='guideline-field' rows={3} placeholder="Scoring rubric / hints for this question" />
                    </Form.Item>
                  </div>
                ))}
                <Button onClick={() => add({ text: '', guideline: '' })}>Add Question</Button>
              </div>
            )}
          </Form.List>

          <Divider/>
          <Form.Item><Button type="primary" htmlType="submit">Create</Button></Form.Item>
        </Form>
      </Card>

      <Card title="Surveys" style={{minWidth:520, flex:1}}>
        <Table rowKey="id" columns={columns} dataSource={surveys} pagination={false}/>
      </Card>

      {selectedId && detail && (
        <Card title={`Survey #${selectedId}: ${detail.survey.title}`} style={{minWidth:520, flex:1}}>
          <Typography.Paragraph>{detail.survey.description}</Typography.Paragraph>

          <Divider orientation="left">Questions</Divider>
          <List
            dataSource={detail.questions}
            renderItem={(q)=>(
              <List.Item style={{display:'block'}}>
                <Space>
                  <Typography.Text strong>#{q.order_index+1}</Typography.Text>
                  <div>{q.text}</div>
                </Space>

                <div style={{marginTop:8}}>
                  <Typography.Text type="secondary">Guideline for this question:</Typography.Text>
                  <Input.TextArea
                    rows={3}
                    style={{marginTop:4}}
                    value={q._guidelineDraft ?? q.guideline?.content ?? ""}
                    onChange={(e)=>{
                      const val = e.target.value
                      setDetail(prev=>{
                        const copy = {...prev}
                        copy.questions = prev.questions.map(qq =>
                          qq.id === q.id ? {...qq, _guidelineDraft: val} : qq
                        )
                        return copy
                      })
                    }}
                    placeholder="Write scoring guideline for this question..."
                  />
                  <div style={{marginTop:6}}>
                    <Space>
                    <Button onClick={async()=>{
                      const content = (q._guidelineDraft ?? q.guideline?.content ?? "").trim()
                      await api.put(`/admin/questions/${q.id}/guideline`, { content })
                      message.success('Guideline saved')
                      await load()
                    }}>
                      Save Guideline
                    </Button>
                    <Button danger onClick={()=>{
                      Modal.confirm({
                        title: 'Delete question?',
                        content: 'This will delete the question and its guideline. This action cannot be undone.',
                        okText: 'Delete',
                        okType: 'danger',
                        onOk: async () => {
                          try {
                            // try to remove guideline first (ignore if not present), then delete the question
                            await api.delete(`/admin/questions/${q.id}/guideline`).catch(()=>{})
                            await api.delete(`/admin/questions/${q.id}`)
                            message.success('Question deleted')
                            await load()
                          } catch (err) {
                            message.error('Failed to delete question')
                          }
                        }
                      })
                    }}>
                      Delete Question
                    </Button>
                    </Space>
                  </div>
                </div>
              </List.Item>
            )}
          />

          <Form layout="inline" form={qForm} onFinish={addQuestion} style={{marginTop:12}}>
            <Form.Item name="text" rules={[{required:true}]}>
              <Input placeholder="New question text" style={{width:360}}/>
            </Form.Item>
            <Form.Item><Button htmlType="submit">Add</Button></Form.Item>
          </Form>



          <Divider/>
          <Space>
            <Button type="primary" onClick={createLink}>Generate Shareable Link</Button>
            <Button onClick={exportCsv}>Export CSV</Button>
            <Button onClick={()=>setSelectedId(null)}>Close</Button>
          </Space>
        </Card>
      )}
    </Space>
  )
}
