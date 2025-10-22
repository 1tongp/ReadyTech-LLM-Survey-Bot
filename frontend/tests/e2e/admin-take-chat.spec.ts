import { test, expect } from '@playwright/test';

/**
 * This test covers the full happy-path:
 * 1) Visit /admin and enter Admin Key
 * 2) Create a survey (2 questions + per-question guidelines)
 * 3) Open survey details, edit a guideline, save
 * 4) Generate a shareable link and extract the token
 * 5) Navigate to /take/<token>, answer/Save/Flag/Unflag/Submit in form mode
 * 6) Navigate to /take/<token>/chat, answer/Save/Submit in chat mode
 */
test('Admin creates survey → generate link → take & chat flows', async ({ page }) => {
    const ADMIN_KEY = process.env.ADMIN_API_KEY ;

    // 1) Admin page: submit admin key
    await page.goto('/admin');
    await page.getByPlaceholder('Admin Key').fill(ADMIN_KEY);
    await page.getByRole('button', { name: /^continue$/i }).click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'e2e-screens/01-admin-after-login.png', fullPage: true });

    // 2) Create survey with two questions and per-question guidelines
    await page.getByLabel('Title').fill('E2E Admin Survey - Playwright Automation Testing');
    await page.getByLabel('Description').fill('E2E created from Playwright');
    await page.waitForTimeout(1000);

    // Fill first question & guideline
    const qFields = page.getByTestId('question-field');
    const guidelineFields = page.getByTestId('guideline-field');
    await page.waitForTimeout(1000);

    await expect(qFields.first()).toBeVisible();
    await expect(guidelineFields.first()).toBeVisible();

    await qFields.first().fill('Q1 must say good');
    await guidelineFields.first().fill('must mention "good" explicitly');
    await page.waitForTimeout(1000);

    // Add a second question
    await page.getByRole('button', { name: /^add question$/i }).click();

    // Fill the last (new) question & guideline
    await qFields.last().fill('Q2 describe impact');
    await guidelineFields.last().fill('mention outcomes and metrics');
    await page.waitForTimeout(1000);

    // Create survey
    await page.getByRole('button', { name: /^Create$/i }).click();
    await expect(page.getByText(/survey created/i)).toBeVisible();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'e2e-screens/02-admin-after-create.png', fullPage: true });

    // 3) Open the survey details and save an updated guideline for Q1
    const row = page.locator('tr').filter({ hasText: 'E2E Admin Survey - Playwright Automation Testing' }).first();
    await row.getByRole('button', { name: /^open$/i }).click();
    await page.waitForTimeout(1000);

    const q1GuidelineTextarea = page
        .getByText('Guideline for this question:', { exact: false })
        .locator('..')
        .locator('textarea')
        .first();

    await q1GuidelineTextarea.fill('must say good; add at least one reason');
    await page.getByRole('button', { name: /^save guideline$/i }).first().click();
    await expect(page.getByText(/guideline saved/i)).toBeVisible();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'e2e-screens/03-admin-detail-after-guideline-save.png', fullPage: true });

    // 4) Generate a shareable link and capture the token from the modal
    await page.getByRole('button', { name: /generate shareable link/i }).click();
    await page.waitForTimeout(1000);

    const modal = page.locator('.ant-modal-content').first();
    await expect(modal.getByText(/^Token:/)).toBeVisible();
    const token = await modal.locator('code').first().innerText();
    expect(token).toBeTruthy();
    await page.screenshot({ path: 'e2e-screens/04-admin-share-link-modal.png', fullPage: true });
    await page.waitForTimeout(1000);

    // Close the modal
    await page.keyboard.press('Escape');

    // 5) Form mode flow at /take/<token>
    await page.goto(`/take/${token}`);

    // Wait for the survey title to appear
    await expect(page.getByText(/E2E Admin Survey - Playwright Automation Testing/i).first()).toBeVisible();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'e2e-screens/05-take-landing.png', fullPage: true });

    // Answer Q1 and save
    await page.getByPlaceholder(/Type your answer/i).fill('This is a good answer with some details.');
    await page.getByRole('button', { name: /^Save$/i }).click();
    await expect(page.getByText(/saved/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/06-take-q1-saved.png', fullPage: true });

    // Next to Q2, answer and save
    await page.getByRole('button', { name: /^Next$/i }).click();
    await page.getByPlaceholder(/Type your answer/i).fill('We improved p95 latency and reduced 500s; outcomes were measurable.');
    await page.getByRole('button', { name: /^Save$/i }).click();
    await expect(page.getByText(/saved/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/07-take-q2-saved.png', fullPage: true });

    // Submit the survey
    await page.getByRole('button', { name: /Submit Survey/i }).click();
    await expect(page.getByText(/submitted\. thank you!/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/08-take-submitted.png', fullPage: true });

    // 6) Chat mode flow
    await page.goto(`/take/${token}/chat`);

    // Expect greeting and first question
    await expect(page.getByText(/welcome! I’ll guide you through/i)).toBeVisible();
    await expect(page.getByText(/Q1\/2:/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/09-chat-landing.png', fullPage: true });

    // Answer Q1 in chat mode
    await page.getByPlaceholder(/Your answer to Q1/i).fill('good again with more details');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/saved\./i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/10-chat-q1-saved.png', fullPage: true });

    // Next to Q2, answer and save
    await page.getByRole('button', { name: /^next$/i }).click();
    await page.getByPlaceholder(/Your answer to Q2/i).fill('impact: latency down, errors down, cost down');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/saved\./i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/11-chat-q2-saved.png', fullPage: true });

    // Submit in chat mode
    await page.getByRole('button', { name: /^submit$/i }).click();
    await expect(page.getByText(/submitted\. thank you!/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/12-chat-submitted.png', fullPage: true });

    // Go back to admin page and delete the survey
    await page.goto('/admin');
    await page.getByPlaceholder('Admin Key').fill(ADMIN_KEY);
    await page.getByRole('button', { name: /^continue$/i }).click();
    await page.waitForTimeout(1000);

    const surveyRow = page.locator('tr').filter({ hasText: 'E2E Admin Survey - Playwright Automation Testing' }).first();
    await surveyRow.getByRole('button', { name: /^delete$/i }).click();
    await expect(page.getByText(/E2E Admin Survey - Playwright Automation Testing/i)).not.toBeVisible();
    await page.screenshot({ path: 'e2e-screens/13-admin-after-delete.png', fullPage: true });
});
