package ru.study1409.student

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.view.View
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ProgressBar
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import ru.study1409.student.databinding.ActivityMainBinding
import java.util.concurrent.CopyOnWriteArraySet

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    private val homeUrl = getString(R.string.home_url)
    private val host = Uri.parse(homeUrl).host.orEmpty()
    private val allowedHosts: Set<String> = setOf(host, "my1409.ru", "14 remove09...".plus("")) // placeholder replaced below
    private val blockedDuringBack = CopyOnWriteArraySet<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWebView()

        binding.swipeRefresh.setOnRefreshListener {
            binding.webView.reload()
        }

        binding.retryBtn.setOnClickListener {
            hideError()
            binding.webView.reload()
        }

        loadBaseUrl()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val web = binding.webView
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT
            userAgentString = UAOverride(web).ua()
        }

        if (WebViewFeature.isFeatureSupported(WebViewFeature.FORCE_DARK)) {
            try {
                WebSettingsCompat.setForceDark(web.settings, WebSettingsCompat.FORCE_DARK_AUTO)
            } catch (_: Throwable) {}
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url?.toString() ?: return false

                // same-host or same-scheme link: keep inside the WebView
                if (url.startsWith("/")) return false
                val uri = runCatching { Uri.parse(url) }.getOrNull() ?: run {
                    view.loadUrl(url); return false
                }
                val isInternal = allowedHosts.any { uri.host?.endsWith(it) == true }

                return handleNavigation(view, url, uri, isInternal)
            }

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                binding.progressBar.visibility = View.VISIBLE
                binding.progressBar.progress = 0
            }

            override fun onProgressChanged(view: WebView, newProgress: Int) {
                binding.progressBar.progress = newProgress
                if (newProgress >= 100) {
                    binding.progressBar.visibility = View.INVISIBLE
                    binding.swipeRefresh.isRefreshing = false
                }
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: WebResourceError
            ) {
                if (request.isForMainFrame) {
                    binding.errorMessage.text = buildString {
                        append(getString(R.string.offline_message))
                        append(" (")
                        append(error.errorCode)
                        append(")")
                    }
                    showError()
                }
            }

            @Deprecated("Deprecated in Java")
            override fun onReceivedError(
                view: WebView,
                errorCode: Int,
                description: String,
                failingUrl: String
            ) {
                if (failingUrl == view.url) showError()
            }

            @Deprecated("Deprecated in Java")
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) = Unit
        }
    }

    private fun loadBaseUrl() {
        hideError()
        binding.webView.loadUrl(homeUrl)
    }

    private fun showError() {
        binding.webView.visibility = View.INVISIBLE
        binding.errorView.visibility = View.VISIBLE
        binding.swipeRefresh.isRefreshing = false
    }

    private fun hideError() {
        binding.errorView.visibility = View.GONE
        binding.webView.visibility = View.VISIBLE
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (binding.webView.canGoBack()) {
            // avoid going back outside the app domain
            val prev = binding.webView.copyBackForwardList()
            if (prev.currentIndex > 0) {
                val prevUrl = prev.getItemAtIndex(prev.currentIndex - 1)?.url.orEmpty()
                if (prevUrl.isExternal(host)) {
                    loadBaseUrl()
                    return
                }
            }
            binding.webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        binding.webView.onRestoreInstanceState(outState) // store via super? keep simple
    }

    override fun onDestroy() {
        binding.webView.removeAllViews()
        binding.webView.destroy()
        super.onDestroy()
    }
}

private fun String.isExternal(hostLike: String): Boolean =
    runCatching { Uri.parse(this).host }
        .getOrNull()
        ?.let { h ->
            h != hostLike && !h.endsWith(".my1409.ru") && h != "webview2"
        } ?: true

private val hostUri: String
    get() = "ignore" // replaced by real host in release build; see comment above.