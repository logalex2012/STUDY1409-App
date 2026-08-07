package ru.study1409.student

import android.annotation.SuppressLint
import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import android.webkit.WebChromeClient
import ru.study1409.student.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    private val homeUrl by lazy { getString(R.string.home_url) }
    private val homeHost by lazy { Uri.parse(homeUrl).host.orEmpty() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWebView()
        setupRefresh()
        requestNotificationPermissionIfNeeded()

        handleIntent(intent)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                    1001
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    @SuppressLint("QueryPermissionsNeeded")
    private fun handleIntent(intent: Intent?) {
        val url = intent?.data?.toString()
        if (url != null && isInternalHost(Uri.parse(url).host.orEmpty())) {
            hideError()
            binding.webView.loadUrl(url)
        } else {
            binding.webView.loadUrl(homeUrl)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val web = binding.webView
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            allowFileAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT

            // Оставляем приложение как есть на внешних сайтах — не лезем
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }

        if (WebViewFeature.isFeatureSupported(WebViewFeature.FORCE_DARK)) {
            runCatching {
                WebSettingsCompat.setForceDark(
                    web.settings,
                    WebSettingsCompat.FORCE_DARK_AUTO
                )
            }
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                val url = request.url?.toString() ?: return false

                // относительные ссылки — оставляем внутри
                if (url.startsWith("/")) return false

                val uri = runCatching { Uri.parse(url) }.getOrNull() ?: return false
                val host = uri.host.orEmpty()

                return if (isInternalHost(host)) {
                    false // грузим внутри приложения
                } else {
                    openExternal(url)
                    true
                }
            }

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                binding.progressBar.visibility = View.VISIBLE
                binding.progressBar.progress = 5
                hideError()
            }

            override fun onPageFinished(view: WebView, url: String?) {
                binding.progressBar.visibility = View.INVISIBLE
                binding.swipeRefresh.isRefreshing = false
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
                if (request.isForMainFrame) showError(error.errorCode)
            }

            @Deprecated("Deprecated in Java")
            override fun onReceivedError(
                view: WebView,
                errorCode: Int,
                description: String?,
                failingUrl: String?
            ) {
                if (failingUrl == view.url) showError(errorCode)
            }

            @Deprecated("Deprecated in Java")
            override fun onReceivedSslError(
                view: WebView,
                handler: SslErrorHandler,
                error: SslError
            ) {
                // не блокируем наш основной хост
                handler.proceed()
            }
        }
    }

    private fun setupRefresh() {
        binding.swipeRefresh.setColorSchemeResources(R.color.accent)
        binding.swipeRefresh.setOnRefreshListener { binding.webView.reload() }
        binding.retryBtn.setOnClickListener {
            hideError()
            binding.webView.reload()
        }
    }

    private fun isInternalHost(host: String): Boolean =
        host == homeHost || host.endsWith(".my1409.ru") || host.endsWith(".my1409.eu")

    private fun openExternal(url: String) = runCatching {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }.onFailure {
        // если не найден браузер — открываем в самом WebView
        binding.webView.loadUrl(url)
    }

    private fun showError(code: Int) {
        binding.errorMessage.text = getString(R.string.offline_message) + " (" + code + ")"
        binding.webView.visibility = View.INVISIBLE
        binding.errorView.visibility = View.VISIBLE
        binding.swipeRefresh.isRefreshing = false
        binding.progressBar.visibility = View.INVISIBLE
    }

    private fun hideError() {
        binding.errorView.visibility = View.GONE
        binding.webView.visibility = View.VISIBLE
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val web = binding.webView
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        binding.webView.removeAllViews()
        binding.webView.destroy()
        super.onDestroy()
    }
}