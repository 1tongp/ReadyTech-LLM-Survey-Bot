import { test, expect } from '@playwright/test';

/**
 * Happy path E2E:
 * 1) Admin login
 * 2) Create survey (2 questions + guidelines)
 * 3) Open survey & save updated guideline
 * 4) Generate share link & capture token
 * 5) Fill /take/<token> (save, next, submit)
 * 6) Fill /take/<token>/chat (save, next, submit)
 * 7) Back to Admin → delete survey (confirm modal)
 */
test('Admin → link → take & chat → delete (confirm modal)', async ({ page }) => {
    const ADMIN_KEY = process.env.ADMIN_API_KEY;

    // 1) Admin login
    await page.goto('/admin');
    await page.getByPlaceholder('Admin Key').fill(ADMIN_KEY!);
    await page.getByRole('button', { name: /^continue$/i }).click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'e2e-screens/01-admin-after-login.png', fullPage: true });

    // 2) Create survey with two questions + guidelines
    await page.getByLabel('Title').fill('E2E Admin Survey - Playwright Automation Testing');
    await page.getByLabel('Description').fill('E2E created from Playwright');
    await page.waitForTimeout(300);

    const qFields = page.getByTestId('question-field');
    const guidelineFields = page.getByTestId('guideline-field');

    await expect(qFields.first()).toBeVisible();
    await expect(guidelineFields.first()).toBeVisible();

    await qFields.first().fill('Q1 must say good');
    await guidelineFields.first().fill('must mention "good" explicitly');

    await page.getByRole('button', { name: /^add question$/i }).click();

    await qFields.last().fill('Q2 describe impact');
    await guidelineFields.last().fill('mention outcomes and metrics');

    await page.getByRole('button', { name: /^create$/i }).click();
    await expect(page.getByText(/survey created/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/02-admin-after-create.png', fullPage: true });

    // 3) Open survey details & save updated guideline for Q1
    const row = page.locator('tr').filter({ hasText: 'E2E Admin Survey - Playwright Automation Testing' }).first();
    await row.getByRole('button', { name: /^open$/i }).click();
    await page.waitForTimeout(300);

    const q1GuidelineTextarea = page
        .getByText('Guideline for this question:', { exact: false })
        .locator('..')
        .locator('textarea')
        .first();

    await q1GuidelineTextarea.fill('must say good; add at least one reason');
    await page.getByRole('button', { name: /^save guideline$/i }).first().click();
    await expect(page.getByText(/guideline saved/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/03-admin-detail-after-guideline-save.png', fullPage: true });

    // 4) Generate shareable link & capture token
    await page.getByRole('button', { name: /generate shareable link/i }).click();
    const modal = page.locator('.ant-modal-content').first();
    await expect(modal.getByText(/^Token:/)).toBeVisible();
    const token = await modal.locator('code').first().innerText();
    expect(token).toBeTruthy();
    await page.screenshot({ path: 'e2e-screens/04-admin-share-link-modal.png', fullPage: true });
    await page.keyboard.press('Escape'); // close modal

    // 5) Form mode flow
    await page.goto(`/take/${token}`);
    await expect(page.getByText(/E2E Admin Survey - Playwright Automation Testing/i).first()).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/05-take-landing.png', fullPage: true });

    await page.getByPlaceholder(/Type your answer/i).fill('This is a good answer with some details.');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/saved/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/06-take-q1-saved.png', fullPage: true });

    await page.getByRole('button', { name: /^next$/i }).click();
    await page.getByPlaceholder(/Type your answer/i).fill('We improved p95 latency and reduced 500s; outcomes were measurable.');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/saved/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/07-take-q2-saved.png', fullPage: true });

    await page.getByRole('button', { name: /submit survey/i }).click();
    await expect(page.getByText(/submitted\. thank you!/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/08-take-submitted.png', fullPage: true });

    // 6) Chat mode flow
    await page.goto(`/take/${token}/chat`);
    await expect(page.getByText(/welcome! I’ll guide you through/i)).toBeVisible();
    await expect(page.getByText(/Q1\/2:/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/09-chat-landing.png', fullPage: true });

    await page.getByPlaceholder(/Your answer to Q1/i).fill('good again with more details');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/saved\./i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/10-chat-q1-saved.png', fullPage: true });

    await page.getByRole('button', { name: /^next$/i }).click();
    await page.getByPlaceholder(/Your answer to Q2/i).fill('impact: latency down, errors down, cost down');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/saved\./i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/11-chat-q2-saved.png', fullPage: true });

    await page.getByRole('button', { name: /^submit$/i }).click();
    await expect(page.getByText(/submitted\. thank you!/i)).toBeVisible();
    await page.screenshot({ path: 'e2e-screens/12-chat-submitted.png', fullPage: true });

    // 7) Back to Admin & delete survey (confirm modal)
    await page.goto('/admin');
    await page.getByPlaceholder('Admin Key').fill(ADMIN_KEY!);
    await page.getByRole('button', { name: /^continue$/i }).click();
    await page.waitForTimeout(300);

    const surveyRow = page.locator('tr').filter({ hasText: 'E2E Admin Survey - Playwright Automation Testing' }).first();
    await surveyRow.getByRole('button', { name: /^delete$/i }).click();

    // NEW: confirm the AntD modal
    const confirmModal = page.locator('.ant-modal-content').filter({ hasText: /Delete survey/i }).first();
    await expect(confirmModal).toBeVisible();
    await confirmModal.getByRole('button', { name: /^delete$/i }).click();

    // Ensure it disappears from the table
    await expect(page.locator('tr', { hasText: 'E2E Admin Survey - Playwright Automation Testing' })).toHaveCount(0);
    await page.screenshot({ path: 'e2e-screens/13-admin-after-delete.png', fullPage: true });
});
